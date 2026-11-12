from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from app.extensions import db, socketio
from app.models.user import User, UserRole
from app.models.tow_truck import TowTruck
from app.models.tow_request import TowRequest, TowRequestStatus
from app.services.dispatch_service import DispatchService
from app.api.geo_routes import validate_coordinates
import logging

logger = logging.getLogger(__name__)
driver_bp = Blueprint('driver_bp', __name__, url_prefix='/api/driver')

@driver_bp.route('/my-truck', methods=['GET'])
@jwt_required()
def get_my_truck():
    """Retorna información y estado de la grúa del chofer autenticado."""
    driver_id = int(get_jwt_identity())
    truck = TowTruck.query.filter_by(driver_id=driver_id).first()
    if not truck:
        return jsonify({'error': 'No tienes una grúa vinculada a tu cuenta de chofer.'}), 404

    return jsonify({'truck': truck.to_dict()}), 200

@driver_bp.route('/toggle-shift', methods=['POST'])
@jwt_required()
def toggle_shift():
    """Activa o desactiva el turno del chofer (En servicio / Fuera de servicio)."""
    driver_id = int(get_jwt_identity())
    truck = TowTruck.query.filter_by(driver_id=driver_id).first()
    if not truck:
        return jsonify({'error': 'No posees una grúa registrada.'}), 404

    data = request.get_json() or {}
    # Si viene explícito lo asignamos, sino alternamos
    if 'is_active' in data:
        truck.is_active = bool(data['is_active'])
    else:
        truck.is_active = not truck.is_active

    db.session.commit()

    socketio.emit('truck_status_update', {
        'truck_id': truck.id,
        'is_available': truck.is_available and truck.is_active,
        'position': {'lat': truck.current_lat, 'lng': truck.current_lng}
    })

    return jsonify({
        'message': f"Turno {'activado' if truck.is_active else 'desactivado'}.",
        'truck': truck.to_dict()
    }), 200

@driver_bp.route('/current-order', methods=['GET'])
@jwt_required()
def get_current_order():
    """Obtiene la solicitud activa asignada o la oferta pendiente para este chofer."""
    driver_id = int(get_jwt_identity())
    truck = TowTruck.query.filter_by(driver_id=driver_id).first()
    if not truck:
        return jsonify({'error': 'Sin grúa vinculada.'}), 404

    # Buscar pedido en curso asignado
    active_order = TowRequest.query.filter(
        TowRequest.truck_id == truck.id,
        TowRequest.status.in_([
            TowRequestStatus.ASSIGNED,
            TowRequestStatus.IN_TRANSIT_TO_USER,
            TowRequestStatus.ARRIVED_AT_USER,
            TowRequestStatus.IN_TRANSIT_TO_DEST
        ])
    ).first()

    if active_order:
        from app.services.geo_service import GeoService
        order_dict = active_order.to_dict()
        target_lat = active_order.dest_lat if (active_order.status == TowRequestStatus.IN_TRANSIT_TO_DEST and active_order.dest_lat is not None) else active_order.origin_lat
        target_lng = active_order.dest_lng if (active_order.status == TowRequestStatus.IN_TRANSIT_TO_DEST and active_order.dest_lng is not None) else active_order.origin_lng
        order_dict['route'] = GeoService.calculate_route(truck.current_lat, truck.current_lng, target_lat, target_lng)
        return jsonify({'type': 'active', 'order': order_dict}), 200

    # Buscar si hay una oferta pendiente de 30s
    pending_offer = TowRequest.query.filter(
        TowRequest.offered_truck_id == truck.id,
        TowRequest.status == TowRequestStatus.OFFERED
    ).first()

    if pending_offer:
        return jsonify({'type': 'offer', 'order': pending_offer.to_dict()}), 200

    return jsonify({'type': 'none', 'order': None}), 200

@driver_bp.route('/respond-offer', methods=['POST'])
@jwt_required()
def respond_offer():
    """Aceptar o rechazar una oferta de despacho entrante."""
    driver_id = int(get_jwt_identity())
    data = request.get_json() or {}

    request_id = data.get('request_id')
    accepted = bool(data.get('accepted', False))

    if not request_id:
        return jsonify({'error': 'request_id requerido.'}), 400

    try:
        result = DispatchService.driver_respond_offer(request_id, driver_id, accepted)
        return jsonify(result), 200
    except (ValueError, PermissionError) as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        logger.error(f"Error respondiendo oferta: {e}")
        return jsonify({'error': 'Error interno al procesar la respuesta.'}), 500

@driver_bp.route('/update-trip-status', methods=['POST'])
@jwt_required()
def update_trip_status():
    """Actualiza la fase del remolque (Hacia el cliente, en sitio, remolcando, finalizado)."""
    driver_id = int(get_jwt_identity())
    data = request.get_json() or {}

    request_id = data.get('request_id')
    new_status = data.get('status')

    if not request_id or not new_status:
        return jsonify({'error': 'request_id y status son obligatorios.'}), 400

    try:
        result = DispatchService.driver_update_trip_status(request_id, driver_id, new_status)
        return jsonify(result), 200
    except (ValueError, PermissionError) as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        logger.error(f"Error en update_trip_status: {e}")
        return jsonify({'error': 'No se pudo actualizar el estado.'}), 500

@driver_bp.route('/telemetry', methods=['POST'])
@jwt_required()
def post_telemetry():
    """
    Endpoint REST para transmitir coordenadas GPS (alternativa o respaldo a WebSocket).
    Protegido contra:
      1. Suplantación de grúa ajena (valida token JWT contra truck.driver_id).
      2. Dispositivos con Mock Location / Fake GPS (is_mocked).
      3. Teletransportación / GPS Spoofing cinemático (velocidad > 180 km/h).
    """
    from flask import current_app
    from app.services.geo_service import GeoService

    driver_id = int(get_jwt_identity())
    truck = TowTruck.query.filter_by(driver_id=driver_id).first()
    if not truck:
        return jsonify({'error': 'Sin grúa vinculada.'}), 404

    data = request.get_json() or {}

    # 1. Validar que no intente reportar coordenadas para otra grúa
    claimed_truck_id = data.get('truck_id')
    if claimed_truck_id is not None and int(claimed_truck_id) != truck.id:
        logger.warning(f"Intento de suplantación REST: Chofer {driver_id} intentó mover grúa #{claimed_truck_id}")
        return jsonify({'error': 'No estás autorizado para actualizar otra unidad.'}), 403

    # 2. Rechazar ubicaciones simuladas por software de Fake GPS
    if data.get('is_mocked') is True:
        logger.warning(f"GPS Spoofing REST bloqueado (is_mocked=True) en grúa #{truck.id}")
        return jsonify({'error': 'Ubicación simulada detectada (Fake GPS no permitido).'}), 403

    lat, lng = validate_coordinates(data.get('lat'), data.get('lng'))
    if lat is None or lng is None:
        return jsonify({'error': 'Coordenadas lat/lng inválidas.'}), 400

    # 3. Validación cinemática de velocidad máxima físicamente posible
    is_dev_sim = bool(data.get('is_dev_sim', False)) and current_app.config.get('DEBUG', False)
    if not is_dev_sim and truck.current_lat is not None and truck.current_lng is not None:
        is_valid, speed_kmh, reason = GeoService.validate_kinematic_movement(
            prev_lat=truck.current_lat,
            prev_lng=truck.current_lng,
            prev_timestamp=truck.last_heartbeat,
            new_lat=lat,
            new_lng=lng
        )
        if not is_valid:
            logger.warning(f"Anomalía cinemática REST en grúa #{truck.id}: {reason}")
            return jsonify({
                'error': reason,
                'speed_kmh': speed_kmh
            }), 400

    truck.update_position(lat, lng)
    db.session.commit()

    # Retransmitir al cliente asignado si tiene pedido activo
    active_req = TowRequest.query.filter(
        TowRequest.truck_id == truck.id,
        TowRequest.status.in_([
            TowRequestStatus.ASSIGNED,
            TowRequestStatus.IN_TRANSIT_TO_USER,
            TowRequestStatus.ARRIVED_AT_USER,
            TowRequestStatus.IN_TRANSIT_TO_DEST
        ])
    ).first()

    eta_info = None
    dist_remaining = None
    if active_req:
        target_point = (
            (active_req.dest_lat, active_req.dest_lng)
            if active_req.status == TowRequestStatus.IN_TRANSIT_TO_DEST and active_req.dest_lat is not None
            else (active_req.origin_lat, active_req.origin_lng)
        )
        dist_remaining = round(GeoService.calculate_distance_km((lat, lng), target_point), 2)
        eta_info = GeoService.calculate_eta(dist_remaining)
        live_payload = {
            'request_id': active_req.id,
            'truck_id': truck.id,
            'position': {'lat': lat, 'lng': lng},
            'target': {'lat': target_point[0], 'lng': target_point[1]},
            'distance_remaining_km': dist_remaining,
            'eta': eta_info,
            'status': active_req.status.value
        }
        socketio.emit('truck_live_location', live_payload, room=f"user_{active_req.client_id}")
        socketio.emit('driver_route_progress', live_payload, room=f"driver_{driver_id}")

    return jsonify({
        'status': 'ok',
        'position': {'lat': lat, 'lng': lng},
        'distance_remaining_km': dist_remaining,
        'eta': eta_info
    }), 200

@driver_bp.route('/simulate-request', methods=['POST'])
@jwt_required()
def simulate_request():
    """Genera una solicitud simulada de auxilio vial dirigida a la grúa del chofer autenticado para pruebas y demos."""
    import uuid
    from datetime import datetime, timezone
    from decimal import Decimal
    from app.services.geo_service import GeoService
    from app.services.currency_service import CurrencyService
    import threading
    from flask import current_app

    driver_id = int(get_jwt_identity())
    truck = TowTruck.query.filter_by(driver_id=driver_id).first()
    if not truck:
        return jsonify({'error': 'No tienes una grúa vinculada.'}), 404

    # Verificar si ya tiene un viaje activo
    active_order = TowRequest.query.filter(
        TowRequest.truck_id == truck.id,
        TowRequest.status.in_([
            TowRequestStatus.ASSIGNED,
            TowRequestStatus.IN_TRANSIT_TO_USER,
            TowRequestStatus.ARRIVED_AT_USER,
            TowRequestStatus.IN_TRANSIT_TO_DEST
        ])
    ).first()
    if active_order:
        return jsonify({'error': 'Ya tienes un viaje activo en curso. Finalízalo antes de simular otro.'}), 400

    # Si hay una oferta pendiente expirada para este camión, cancelarla
    old_offer = TowRequest.query.filter_by(offered_truck_id=truck.id, status=TowRequestStatus.OFFERED).first()
    if old_offer:
        old_offer.status = TowRequestStatus.CANCELLED
        db.session.commit()

    # Asegurar que el camión esté disponible y activo para pruebas
    truck.is_active = True
    truck.is_available = True
    db.session.commit()

    # Buscar usuario cliente demo para la simulación
    client = User.query.filter_by(role=UserRole.CLIENT).first()
    if not client:
        client = User(
            email='cliente.sim@josepo.com',
            full_name='Carlos Cliente (Demo SOS)',
            phone_number='+584149998877',
            role=UserRole.CLIENT
        )
        client.set_password('Cliente2026!')
        db.session.add(client)
        db.session.commit()

    # Coordenadas simuladas cerca de la grúa (+ ~1.8 km)
    client_lat = round(truck.current_lat + 0.012, 6)
    client_lng = round(truck.current_lng + 0.008, 6)
    dest_lat = round(truck.current_lat + 0.045, 6)
    dest_lng = round(truck.current_lng + 0.030, 6)

    req_uuid = str(uuid.uuid4())
    dist_to_user = GeoService.calculate_distance_km((client_lat, client_lng), (truck.current_lat, truck.current_lng))
    trip_dist = GeoService.calculate_distance_km((client_lat, client_lng), (dest_lat, dest_lng))
    total_dist = dist_to_user + trip_dist
    cost_data = CurrencyService.calculate_cost(total_dist)

    origin_addr = f"Autopista / Av. Principal (a {round(dist_to_user, 1)} km)"
    dest_addr = "Taller Mecánico Especializado / Residencia"

    new_request = TowRequest(
        id=req_uuid,
        client_id=client.id,
        truck_id=None,
        offered_truck_id=truck.id,
        offered_at=datetime.now(timezone.utc),
        offer_timeout_seconds=DispatchService.OFFER_TIMEOUT_SECONDS,
        rejected_truck_ids=[],
        status=TowRequestStatus.OFFERED,
        origin_lat=client_lat,
        origin_lng=client_lng,
        origin_address=origin_addr,
        dest_lat=dest_lat,
        dest_lng=dest_lng,
        dest_address=dest_addr,
        distance_to_user_km=dist_to_user,
        trip_distance_km=trip_dist,
        total_distance_km=total_dist,
        cost_ves_cents=cost_data['cost_ves_cents'],
        cost_usd_cents=cost_data['cost_usd_cents'],
        exchange_rate=Decimal(str(cost_data['exchange_rate'])),
        payment_status='HELD_IN_ESCROW'
    )

    db.session.add(new_request)
    db.session.commit()

    # Emitir por WebSocket al chofer
    DispatchService._send_dispatch_offer(new_request, truck)

    # Iniciar temporizador SLA de 30 segundos
    app_obj = current_app._get_current_object()
    threading.Thread(
        target=DispatchService._watch_offer_timeout,
        args=(app_obj, new_request.id, truck.id),
        daemon=True
    ).start()

    return jsonify({
        'message': 'Pedido de prueba generado y emitido exitosamente.',
        'request': new_request.to_dict()
    }), 201
