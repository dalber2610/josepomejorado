import uuid
from decimal import Decimal
from datetime import datetime, timezone
import threading
import time
import logging
from flask import current_app
from app.extensions import db, socketio
from app.models.tow_truck import TowTruck
from app.models.tow_request import TowRequest, TowRequestStatus
from app.services.geo_service import GeoService
from app.services.currency_service import CurrencyService

logger = logging.getLogger(__name__)

class DispatchService:
    """Motor de despacho bidireccional inteligente con SLA de 30 segundos y rotación automática."""

    OFFER_TIMEOUT_SECONDS = 30

    @classmethod
    def estimate_service(cls, origin_lat: float, origin_lng: float, dest_lat: float = None, dest_lng: float = None) -> dict:
        """Calcula una cotización estimada antes de confirmar la solicitud."""
        available_trucks = TowTruck.query.filter_by(is_available=True, is_active=True).all()
        if not available_trucks:
            return {'available': False, 'message': 'No hay unidades de grúa en servicio disponibles en este momento.'}

        user_origin = (origin_lat, origin_lng)
        truck_distances = [
            (truck, GeoService.calculate_distance_km(user_origin, (truck.current_lat, truck.current_lng)))
            for truck in available_trucks
        ]
        closest_truck, dist_to_user = min(truck_distances, key=lambda x: x[1])

        trip_dist = 0.0
        if dest_lat is not None and dest_lng is not None:
            trip_dist = GeoService.calculate_distance_km(user_origin, (dest_lat, dest_lng))

        total_distance = dist_to_user + trip_dist
        cost_breakdown = CurrencyService.calculate_cost(total_distance)
        eta_info = GeoService.calculate_eta(dist_to_user)

        return {
            'available': True,
            'nearest_truck_id': closest_truck.id,
            'nearest_truck_plate': closest_truck.license_plate,
            'nearest_truck_position': {
                'lat': closest_truck.current_lat,
                'lng': closest_truck.current_lng
            },
            'distance_to_user_km': round(dist_to_user, 2),
            'trip_distance_km': round(trip_dist, 2),
            'total_distance_km': round(total_distance, 2),
            'eta': eta_info,
            'pricing': cost_breakdown
        }

    @classmethod
    def request_tow_with_offer(cls, client_id: int, origin_lat: float, origin_lng: float,
                                dest_lat: float = None, dest_lng: float = None,
                                request_id: str = None) -> TowRequest:
        """
        Inicia el proceso de solicitud mediante oferta bidireccional:
        Localiza la grúa más cercana y le envía la oferta con un contador de 30 segundos.
        """
        user_origin = (origin_lat, origin_lng)
        req_uuid = request_id or str(uuid.uuid4())

        existing = TowRequest.query.filter_by(id=req_uuid).first()
        if existing:
            return existing

        # Verificar si el cliente ya tiene un servicio no completado
        active_request = TowRequest.query.filter(
            TowRequest.client_id == client_id,
            TowRequest.status.in_([
                TowRequestStatus.PENDING,
                TowRequestStatus.OFFERED,
                TowRequestStatus.ASSIGNED,
                TowRequestStatus.IN_TRANSIT_TO_USER,
                TowRequestStatus.ARRIVED_AT_USER,
                TowRequestStatus.IN_TRANSIT_TO_DEST
            ])
        ).first()

        if active_request:
            raise ValueError("Ya posees un servicio de grúa en curso o en espera de asignación.")

        available_trucks = TowTruck.query.filter_by(is_available=True, is_active=True).all()
        if not available_trucks:
            raise RuntimeError("No hay grúas disponibles en tu área en este momento.")

        # Buscar la grúa más cercana
        truck_distances = [
            (truck, GeoService.calculate_distance_km(user_origin, (truck.current_lat, truck.current_lng)))
            for truck in available_trucks
        ]
        chosen_truck, dist_to_user = min(truck_distances, key=lambda x: x[1])

        trip_dist = 0.0
        if dest_lat is not None and dest_lng is not None:
            trip_dist = GeoService.calculate_distance_km(user_origin, (dest_lat, dest_lng))

        total_dist = dist_to_user + trip_dist
        cost_data = CurrencyService.calculate_cost(total_dist)

        origin_addr = GeoService.reverse_geocode(origin_lat, origin_lng)
        dest_addr = GeoService.reverse_geocode(dest_lat, dest_lng) if dest_lat and dest_lng else None

        new_request = TowRequest(
            id=req_uuid,
            client_id=client_id,
            truck_id=None,
            offered_truck_id=chosen_truck.id,
            offered_at=datetime.now(timezone.utc),
            offer_timeout_seconds=cls.OFFER_TIMEOUT_SECONDS,
            rejected_truck_ids=[],
            status=TowRequestStatus.OFFERED,
            origin_lat=origin_lat,
            origin_lng=origin_lng,
            origin_address=origin_addr,
            dest_lat=dest_lat,
            dest_lng=dest_lng,
            dest_address=dest_addr,
            distance_to_user_km=dist_to_user,
            trip_distance_km=trip_dist,
            total_distance_km=total_dist,
            cost_ves_cents=cost_data['cost_ves_cents'],
            cost_usd_cents=cost_data['cost_usd_cents'],
            exchange_rate=Decimal(str(cost_data['exchange_rate']))
        )

        db.session.add(new_request)
        db.session.commit()

        # Emitir la oferta a la pantalla del chofer
        cls._send_dispatch_offer(new_request, chosen_truck)

        # Iniciar hilo de vigilancia del SLA de 30 segundos
        app_obj = current_app._get_current_object()
        threading.Thread(
            target=cls._watch_offer_timeout,
            args=(app_obj, new_request.id, chosen_truck.id),
            daemon=True
        ).start()

        return new_request

    @classmethod
    def driver_respond_offer(cls, request_id: str, driver_id: int, accepted: bool) -> dict:
        """
        Procesa la respuesta (Aceptar o Rechazar) enviada por el chofer.
        Mitigación Hallazgo C: Bloqueo atómico de fila `with_for_update()` para evitar
        condiciones de carrera donde dos grúas acepten el mismo servicio en el mismo milisegundo.
        """
        tow_req = TowRequest.query.filter_by(id=request_id).with_for_update().first()
        if not tow_req:
            raise ValueError("Solicitud no encontrada.")

        driver_truck = TowTruck.query.filter_by(driver_id=driver_id).with_for_update().first()
        if not driver_truck or tow_req.offered_truck_id != driver_truck.id:
            raise PermissionError("Esta oferta no corresponde a tu unidad de grúa.")

        if tow_req.status != TowRequestStatus.OFFERED or tow_req.truck_id is not None:
            return {'status': 'expired', 'message': 'La oferta ya no se encuentra activa o fue asignada.'}

        if accepted:
            if not driver_truck.is_available:
                raise ValueError("Tu unidad ya tiene otro servicio asignado en curso.")

            # Chofer ACEPTÓ: Asignación definitiva bajo bloqueo transaccional
            tow_req.status = TowRequestStatus.ASSIGNED
            tow_req.truck_id = driver_truck.id
            tow_req.offered_truck_id = None
            driver_truck.is_available = False

            # Vincular al chofer en cualquier pago en garantía preexistente
            from app.models.payment import Payment
            existing_payment = Payment.query.filter_by(request_id=tow_req.id).with_for_update().first()
            if existing_payment and driver_truck.driver_id:
                existing_payment.driver_id = driver_truck.driver_id

            db.session.commit()

            # Calcular ruta vial exacta desde la posición de la grúa hasta el sitio del incidente
            route_data = GeoService.calculate_route(
                driver_truck.current_lat,
                driver_truck.current_lng,
                tow_req.origin_lat,
                tow_req.origin_lng
            )
            req_dict = tow_req.to_dict()
            req_dict['route'] = route_data

            # Notificar al cliente solicitante con la ruta exacta y el ETA
            socketio.emit('tow_assigned', req_dict, room=f"user_{tow_req.client_id}")

            # Notificar al público que la grúa ahora está ocupada
            socketio.emit('truck_status_update', {
                'truck_id': driver_truck.id,
                'is_available': False,
                'position': {'lat': driver_truck.current_lat, 'lng': driver_truck.current_lng}
            })

            return {'status': 'assigned', 'request': req_dict}

        else:
            # Chofer RECHAZÓ: Añadir a lista de rechazadas y rotar
            logger.info(f"Chofer {driver_id} rechazó el pedido {request_id}. Rotando oferta...")
            rejected = list(tow_req.rejected_truck_ids or [])
            rejected.append(driver_truck.id)
            tow_req.rejected_truck_ids = rejected
            db.session.commit()

            cls.rotate_offer(tow_req.id)
            return {'status': 'rejected', 'message': 'Oferta rechazada. El pedido rotará a la siguiente grúa.'}

    @classmethod
    def rotate_offer(cls, request_id: str):
        """Rota la solicitud a la siguiente grúa más cercana disponible que no haya rechazado."""
        tow_req = TowRequest.query.filter_by(id=request_id).with_for_update().first()
        if not tow_req or tow_req.status != TowRequestStatus.OFFERED:
            return

        rejected_ids = tow_req.rejected_truck_ids or []
        available_trucks = TowTruck.query.filter(
            TowTruck.is_available == True,
            TowTruck.is_active == True,
            TowTruck.id.notin_(rejected_ids)
        ).all()

        if not available_trucks:
            # No quedan más grúas disponibles en el radio
            tow_req.status = TowRequestStatus.TIMEOUT_NO_DRIVERS
            tow_req.offered_truck_id = None
            db.session.commit()

            # Fase 3: Reembolsar garantía de pago retenida si no hay grúas
            from app.services.payment_service import PaymentService
            PaymentService.refund_escrow(request_id, reason="No se encontraron unidades de grúa disponibles")

            socketio.emit('tow_failed_no_drivers', {
                'request_id': tow_req.id,
                'message': 'No se encontraron unidades de grúa disponibles para aceptar tu solicitud en este momento.'
            }, room=f"user_{tow_req.client_id}")
            return

        # Seleccionar la siguiente más cercana
        user_origin = (tow_req.origin_lat, tow_req.origin_lng)
        truck_distances = [
            (truck, GeoService.calculate_distance_km(user_origin, (truck.current_lat, truck.current_lng)))
            for truck in available_trucks
        ]
        next_truck, dist_to_user = min(truck_distances, key=lambda x: x[1])

        tow_req.offered_truck_id = next_truck.id
        tow_req.offered_at = datetime.now(timezone.utc)
        tow_req.distance_to_user_km = dist_to_user
        tow_req.total_distance_km = dist_to_user + tow_req.trip_distance_km

        db.session.commit()

        # Emitir la oferta al nuevo chofer
        cls._send_dispatch_offer(tow_req, next_truck)

        # Iniciar temporizador de 30 segundos para la nueva grúa
        app_obj = current_app._get_current_object()
        threading.Thread(
            target=cls._watch_offer_timeout,
            args=(app_obj, tow_req.id, next_truck.id),
            daemon=True
        ).start()

    @classmethod
    def _watch_offer_timeout(cls, app_obj, request_id: str, offered_truck_id: int):
        """Monitorea si el chofer no responde dentro de los 30 segundos de SLA."""
        time.sleep(cls.OFFER_TIMEOUT_SECONDS)
        with app_obj.app_context():
            tow_req = TowRequest.query.filter_by(id=request_id).with_for_update().first()
            if not tow_req:
                return

            # Si sigue en estado OFFERED con la misma grúa ofrecida, expiró el tiempo
            if tow_req.status == TowRequestStatus.OFFERED and tow_req.offered_truck_id == offered_truck_id:
                logger.warning(f"SLA Vencido (30s) para grúa {offered_truck_id} en pedido {request_id}. Rotando...")
                
                # Notificar a la grúa que la oferta expiró
                truck = db.session.get(TowTruck, offered_truck_id)
                if truck and truck.driver_id:
                    socketio.emit('dispatch_offer_timeout', {
                        'request_id': request_id,
                        'message': 'Tiempo agotado (30s). La solicitud ha sido reasignada.'
                    }, room=f"driver_{truck.driver_id}")

                rejected = list(tow_req.rejected_truck_ids or [])
                rejected.append(offered_truck_id)
                tow_req.rejected_truck_ids = rejected
                db.session.commit()

                cls.rotate_offer(request_id)

    @classmethod
    def _send_dispatch_offer(cls, req: TowRequest, truck: TowTruck):
        """Emite el evento WebSocket con sonido y datos a la consola móvil del chofer."""
        if not truck.driver_id:
            return

        eta_info = GeoService.calculate_eta(req.distance_to_user_km)
        payload = {
            'request_id': req.id,
            'client_name': req.client.full_name if req.client else 'Cliente en emergencia',
            'client_phone': req.client.phone_number if req.client else '',
            'origin': {
                'lat': req.origin_lat,
                'lng': req.origin_lng,
                'address': req.origin_address
            },
            'destination': {
                'lat': req.dest_lat,
                'lng': req.dest_lng,
                'address': req.dest_address
            } if req.dest_lat is not None else None,
            'distance_to_user_km': round(req.distance_to_user_km, 2),
            'trip_distance_km': round(req.trip_distance_km, 2),
            'total_distance_km': round(req.total_distance_km, 2),
            'eta': eta_info,
            'cost_ves': round(req.cost_ves_cents / 100.0, 2),
            'cost_usd': round(req.cost_usd_cents / 100.0, 2),
            'driver_net_ves': round((req.cost_ves_cents * 0.85) / 100.0, 2),
            'driver_net_usd': round((req.cost_usd_cents * 0.85) / 100.0, 2),
            'payment_status': req.payment_status,
            'has_escrow': req.payment_status == 'HELD_IN_ESCROW',
            'timeout_seconds': cls.OFFER_TIMEOUT_SECONDS,
            'offered_at': req.offered_at.isoformat() if req.offered_at else datetime.now(timezone.utc).isoformat()
        }

        socketio.emit('dispatch_offer', payload, room=f"driver_{truck.driver_id}")

        # Avisar al cliente que estamos contactando a la grúa más cercana
        socketio.emit('tow_contacting_driver', {
            'request_id': req.id,
            'truck_id': truck.id,
            'plate': truck.license_plate,
            'truck_position': {'lat': truck.current_lat, 'lng': truck.current_lng},
            'eta': eta_info,
            'message': f'Contactando a la grúa {truck.license_plate} a {round(req.distance_to_user_km, 1)} km (~{eta_info["eta_formatted"]})...'
        }, room=f"user_{req.client_id}")

    @classmethod
    def driver_update_trip_status(cls, request_id: str, driver_id: int, new_status_str: str) -> dict:
        """Transición de estados del traslado por parte del chofer con bloqueo transaccional."""
        driver_truck = TowTruck.query.filter_by(driver_id=driver_id).with_for_update().first()
        if not driver_truck:
            raise PermissionError("No posees una grúa registrada.")

        tow_req = TowRequest.query.filter_by(id=request_id, truck_id=driver_truck.id).with_for_update().first()
        if not tow_req:
            raise ValueError("Servicio activo no encontrado.")

        if new_status_str not in TowRequestStatus.__members__:
            raise ValueError("Estado no válido.")

        new_status = TowRequestStatus[new_status_str]
        tow_req.status = new_status

        if new_status == TowRequestStatus.COMPLETED:
            tow_req.completed_at = datetime.now(timezone.utc)
            driver_truck.is_available = True
            db.session.commit()

            # Fase 3: Liberar garantía de pago en Escrow directamente al chofer
            from app.services.payment_service import PaymentService
            PaymentService.release_escrow_to_driver(request_id)

            # Fase 5: Acreditar puntos de reputación por servicio completado (+50 pts)
            try:
                from app.services.gamification_service import GamificationService
                GamificationService.award_points(
                    user_id=tow_req.client_id,
                    points=GamificationService.POINTS_COMPLETE_TOW,
                    reason_code='TOW_COMPLETED',
                    description=f"Servicio de auxilio vial completado (#{tow_req.id[:8]})",
                    reference_id=tow_req.id
                )
                GamificationService.award_points(
                    user_id=driver_id,
                    points=GamificationService.POINTS_COMPLETE_TOW,
                    reason_code='TOW_COMPLETED',
                    description=f"Rescate vial exitoso completado en unidad {driver_truck.license_plate}",
                    reference_id=tow_req.id
                )
            except Exception as ge:
                logger.warning(f"No se pudieron acreditar puntos de gamificación al completar viaje: {ge}")
        else:
            db.session.commit()

        # Calcular ruta actualizada según la etapa del servicio
        route_data = None
        if new_status == TowRequestStatus.IN_TRANSIT_TO_USER:
            route_data = GeoService.calculate_route(
                driver_truck.current_lat, driver_truck.current_lng,
                tow_req.origin_lat, tow_req.origin_lng
            )
        elif new_status == TowRequestStatus.IN_TRANSIT_TO_DEST and tow_req.dest_lat is not None and tow_req.dest_lng is not None:
            route_data = GeoService.calculate_route(
                driver_truck.current_lat, driver_truck.current_lng,
                tow_req.dest_lat, tow_req.dest_lng
            )
        elif new_status == TowRequestStatus.ARRIVED_AT_USER:
            route_data = GeoService.calculate_route(
                tow_req.origin_lat, tow_req.origin_lng,
                tow_req.origin_lat, tow_req.origin_lng
            )

        # Notificar al cliente solicitante
        socketio.emit('tow_status_changed', {
            'request_id': tow_req.id,
            'new_status': new_status.value,
            'route': route_data,
            'timestamp': datetime.now(timezone.utc).isoformat()
        }, room=f"user_{tow_req.client_id}")

        if new_status == TowRequestStatus.COMPLETED:
            socketio.emit('truck_status_update', {
                'truck_id': driver_truck.id,
                'is_available': True,
                'position': {'lat': driver_truck.current_lat, 'lng': driver_truck.current_lng}
            })

        return {'status': 'success', 'new_status': new_status.value, 'route': route_data}

    @classmethod
    def cancel_request(cls, request_id: str, user_id: int) -> TowRequest:
        """Cancela la solicitud activa y libera la grúa con bloqueo transaccional."""
        tow_req = TowRequest.query.filter_by(id=request_id).with_for_update().first()
        if not tow_req:
            raise ValueError("Solicitud no encontrada.")

        if tow_req.client_id != user_id:
            raise PermissionError("No tienes permisos para cancelar esta solicitud.")

        if tow_req.status in [TowRequestStatus.COMPLETED, TowRequestStatus.CANCELLED]:
            raise ValueError("La solicitud ya ha finalizado.")

        tow_req.status = TowRequestStatus.CANCELLED
        
        # Fase 3: Reembolsar garantía de pago retenida por cancelación
        from app.services.payment_service import PaymentService
        PaymentService.refund_escrow(request_id, reason="Cancelación solicitada por el cliente")

        if tow_req.assigned_truck:
            tow_req.assigned_truck.is_available = True
            socketio.emit('tow_cancelled', {
                'request_id': tow_req.id,
                'message': 'El cliente ha cancelado el servicio.'
            }, room=f"driver_{tow_req.assigned_truck.driver_id}")

        db.session.commit()

        if tow_req.assigned_truck:
            socketio.emit('truck_status_update', {
                'truck_id': tow_req.assigned_truck.id,
                'is_available': True,
                'position': {
                    'lat': tow_req.assigned_truck.current_lat,
                    'lng': tow_req.assigned_truck.current_lng
                }
            })

        return tow_req
