from datetime import datetime, timezone
import logging
from app.extensions import db, socketio
from app.models.service_contract import ServiceContract
from app.models.tow_request import TowRequest, TowRequestStatus
from app.models.tow_truck import TowTruck

logger = logging.getLogger(__name__)


class ContractService:
    """Motor de inspección vehicular, auditoría de SLA y contratos digitales con valor legal."""

    SLA_STANDARD_ARRIVAL_MINUTES = 30

    @classmethod
    def register_vehicle_inspection(cls, request_id: str, driver_id: int,
                                    vehicle_plate: str, vehicle_model: str,
                                    vehicle_color: str = None, pre_existing_damages: str = None) -> ServiceContract:
        """
        Registra el acta de inspección vehicular en el momento exacto en que la grúa hace contacto
        con el auto accidentado. Protege judicialmente a la empresa y al chofer contra falsos reclamos.
        Usa bloqueo transaccional `with_for_update()` (Hallazgo C).
        """
        tow_req = TowRequest.query.filter_by(id=request_id).with_for_update().first()
        if not tow_req:
            raise ValueError("Solicitud de remolque no encontrada.")

        driver_truck = TowTruck.query.filter_by(driver_id=driver_id).with_for_update().first()
        if not driver_truck or tow_req.truck_id != driver_truck.id:
            raise PermissionError("Solo el conductor asignado a este servicio puede registrar la inspección.")

        now = datetime.now(timezone.utc)

        # Calcular auditoría de SLA (Tiempo real de llegada al sitio del siniestro)
        created_at = tow_req.created_at
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
            
        elapsed_seconds = (now - created_at).total_seconds()
        actual_minutes = max(1, int(elapsed_seconds / 60.0))
        sla_met = actual_minutes <= cls.SLA_STANDARD_ARRIVAL_MINUTES

        # Generar firma digital de recepción
        signer = driver_truck.driver.full_name if driver_truck.driver else f"Conductor #{driver_id}"
        reception_hash = ServiceContract.generate_signature_hash(signer, request_id, now)

        contract = ServiceContract.query.filter_by(request_id=request_id).with_for_update().first()
        if contract and contract.delivery_signature_hash is not None:
            raise ValueError("El contrato ya fue cerrado y firmado por el cliente; no admite modificaciones posteriores.")

        if not contract:
            contract = ServiceContract(
                request_id=request_id,
                vehicle_plate=vehicle_plate.strip().upper(),
                vehicle_model=vehicle_model.strip(),
                vehicle_color=vehicle_color.strip() if vehicle_color else 'No especificado',
                pre_existing_damages=pre_existing_damages.strip() if pre_existing_damages else 'Sin daños previos reportados.',
                sla_target_minutes=cls.SLA_STANDARD_ARRIVAL_MINUTES,
                sla_actual_minutes=actual_minutes,
                sla_met=sla_met,
                reception_signature_hash=reception_hash,
                created_at=now
            )
            db.session.add(contract)
        else:
            contract.vehicle_plate = vehicle_plate.strip().upper()
            contract.vehicle_model = vehicle_model.strip()
            if vehicle_color:
                contract.vehicle_color = vehicle_color.strip()
            if pre_existing_damages:
                contract.pre_existing_damages = pre_existing_damages.strip()
            contract.sla_actual_minutes = actual_minutes
            contract.sla_met = sla_met
            contract.reception_signature_hash = reception_hash

        db.session.commit()

        # Emitir notificación en tiempo real al cliente con el acta levantada
        socketio.emit('contract_inspection_registered', {
            'request_id': request_id,
            'contract': contract.to_dict(),
            'message': f"Inspección completada para auto {contract.vehicle_plate}. SLA: {actual_minutes} min ({'Cumplido ✓' if sla_met else 'Excedido'})."
        }, room=f"user_{tow_req.client_id}")

        return contract

    @classmethod
    def client_sign_and_rate(cls, request_id: str, client_id: int,
                             rating: int, feedback: str = None) -> ServiceContract:
        """
        El cliente califica el servicio al finalizar el remolque y sella digitalmente la entrega
        conforme a su aseguradora o taller con bloqueo transaccional `with_for_update()`.
        """
        tow_req = TowRequest.query.filter_by(id=request_id).with_for_update().first()
        if not tow_req:
            raise ValueError("Solicitud no encontrada.")

        if tow_req.client_id != client_id:
            raise PermissionError("Solo el cliente contratante puede firmar la conformidad y calificar.")

        contract = ServiceContract.query.filter_by(request_id=request_id).with_for_update().first()
        if contract and contract.delivery_signature_hash is not None:
            raise ValueError("El acta de entrega de este servicio ya fue firmada y sellada previamente.")

        if not contract:
            contract = ServiceContract(
                request_id=request_id,
                vehicle_plate='AUTOMÓVIL',
                vehicle_model='Modelo registrado por cliente'
            )
            db.session.add(contract)

        now = datetime.now(timezone.utc)
        signer_name = tow_req.client.full_name if tow_req.client else f"Cliente #{client_id}"
        delivery_hash = ServiceContract.generate_signature_hash(signer_name, request_id, now)

        contract.delivery_signature_hash = delivery_hash
        contract.delivered_at = now
        contract.client_rating = max(1, min(5, int(rating)))
        if feedback:
            contract.client_feedback = feedback.strip()

        db.session.commit()

        # Notificar al chofer la calificación recibida
        if tow_req.assigned_truck and tow_req.assigned_truck.driver_id:
            socketio.emit('service_rated_by_client', {
                'request_id': request_id,
                'rating': contract.client_rating,
                'feedback': contract.client_feedback,
                'message': f"¡Has recibido {contract.client_rating} estrellas de calificación!"
            }, room=f"driver_{tow_req.assigned_truck.driver_id}")

        return contract

    @classmethod
    def get_contract_by_token(cls, token: str) -> dict:
        """Busca y certifica la validez legal del acta digital para compañías aseguradoras."""
        contract = ServiceContract.query.filter_by(digital_receipt_token=token).first()
        if not contract:
            return None

        tow_req = contract.request
        return {
            'certified': True,
            'token': contract.digital_receipt_token,
            'contract': contract.to_dict(),
            'service_summary': {
                'client': tow_req.client.full_name if tow_req.client else 'Cliente',
                'driver': tow_req.assigned_truck.driver.full_name if (tow_req.assigned_truck and tow_req.assigned_truck.driver) else 'Conductor',
                'truck_plate': tow_req.assigned_truck.license_plate if tow_req.assigned_truck else 'N/A',
                'origin': tow_req.origin_address or f"Coord ({tow_req.origin_lat}, {tow_req.origin_lng})",
                'destination': tow_req.dest_address or 'Destino final convenido',
                'total_distance_km': tow_req.total_distance_km,
                'cost_usd': round(tow_req.cost_usd_cents / 100.0, 2),
                'cost_ves': round(tow_req.cost_ves_cents / 100.0, 2),
                'status': tow_req.status.value,
                'payment_status': tow_req.payment_status
            }
        }
