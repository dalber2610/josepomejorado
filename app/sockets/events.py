from flask import request, current_app
from flask_socketio import emit, join_room
from flask_jwt_extended import decode_token
from app.extensions import socketio, db
from app.models.user import User, UserRole
from app.models.tow_truck import TowTruck
from app.models.tow_request import TowRequest, TowRequestStatus
from app.services.dispatch_service import DispatchService
from app.services.geo_service import GeoService
from datetime import datetime, timezone
import logging

logger = logging.getLogger(__name__)

# Mapeo de conexión de sockets en memoria
connected_clients = {}

# Caché en memoria de telemetría por grúa para Throttling de escrituras en BD (Hallazgo B)
# y validación cinemática en tiempo real (Hallazgo E)
# Estructura: { truck_id: {'lat': float, 'lng': float, 'timestamp': datetime, 'last_db_commit': datetime} }
_truck_telemetry_cache = {}


def reset_telemetry_cache():
    """Limpia la caché de telemetría (útil para pruebas unitarias)."""
    _truck_telemetry_cache.clear()


@socketio.on('connect')
def handle_connect(auth=None):
    """
    Manejo de conexión con autenticación JWT verificada.
    Permite a los usuarios y choferes unirse a sus salas privadas seguras.
    """
    token = None
    if isinstance(auth, dict) and 'token' in auth:
        token = auth['token']
    elif 'token' in request.args:
        token = request.args.get('token')

    user = None
    token_exp = None
    if token:
        try:
            decoded = decode_token(token)
            user_id = int(decoded['sub'])
            token_exp = decoded.get('exp')
            user = db.session.get(User, user_id)
        except Exception as e:
            logger.warning(f"Conexión con token inválido: {e}")

    sid = request.sid
    connected_clients[sid] = {
        'user_id': user.id if user else None,
        'role': user.role.value if user else 'ANONYMOUS',
        'token_exp': token_exp,
        'connected_at': datetime.now(timezone.utc).isoformat()
    }

    if user:
        user_room = f"user_{user.id}"
        join_room(user_room)
        
        if user.role == UserRole.DRIVER:
            driver_room = f"driver_{user.id}"
            join_room(driver_room)
            logger.info(f"Chofer {user.full_name} conectado (SID: {sid}, Sala: {driver_room})")
        else:
            logger.info(f"Cliente {user.full_name} conectado (SID: {sid}, Sala: {user_room})")
    else:
        logger.info(f"Cliente anónimo conectado (SID: {sid})")

    emit('connection_success', {
        'message': 'Conectado al servidor de tiempo real de Josepo.',
        'authenticated': user is not None,
        'user_id': user.id if user else None,
        'role': user.role.value if user else 'ANONYMOUS'
    })


@socketio.on('disconnect')
def handle_disconnect():
    """Limpia el estado del cliente al desconectarse."""
    sid = request.sid
    client_info = connected_clients.pop(sid, None)
    if client_info and client_info['user_id']:
        logger.info(f"Usuario {client_info['user_id']} desconectado.")


@socketio.on('driver_respond_offer')
def handle_driver_offer_response(data):
    """El chofer responde en tiempo real a una oferta (Aceptar / Rechazar)."""
    sid = request.sid
    client_info = connected_clients.get(sid)
    if not client_info or client_info.get('role') != 'DRIVER':
        emit('error', {'message': 'No autorizado.'})
        return

    driver_id = client_info['user_id']
    request_id = data.get('request_id')
    accepted = bool(data.get('accepted', False))

    try:
        result = DispatchService.driver_respond_offer(request_id, driver_id, accepted)
        emit('offer_response_acknowledged', result)
    except Exception as e:
        logger.error(f"Error en driver_respond_offer (WebSocket): {e}")
        emit('error', {'message': str(e)})


@socketio.on('update_driver_position')
def handle_driver_position(data):
    """
    Evento para que los choferes de grúa transmitan su telemetría GPS real.
    Mitigaciones implementadas:
    - Hallazgo E: Validación de sesión JWT vigente, propiedad estricta del TowTruck,
      detección de bandera `is_mocked` y filtro cinemático Anti-GPS Spoofing (<= 180 km/h).
    - Hallazgo B: Coalescing / Throttling de escrituras en base de datos para evitar
      bloqueos de concurrencia ('Database Is Locked') bajo ráfagas de telemetría.
    """
    sid = request.sid
    client_info = connected_clients.get(sid)
    
    if not client_info or not client_info.get('user_id') or client_info.get('role') != 'DRIVER':
        emit('error', {'message': 'Acción no autorizada: Solo conductores con JWT válido pueden transmitir posición.'})
        return

    now = datetime.now(timezone.utc)

    # Verificar que el token JWT con el que se abrió el socket no haya expirado
    token_exp = client_info.get('token_exp')
    if token_exp and now.timestamp() > float(token_exp):
        emit('error', {'message': 'Sesión JWT expirada. Reconecte con un token válido.'})
        return

    # Rechazar ubicaciones simuladas por apps de Fake GPS reportadas por el SO móvil
    if isinstance(data, dict) and data.get('is_mocked') is True:
        logger.warning(f"🚨 [SECURITY ALERT - FAKE GPS] Conductor {client_info['user_id']} bloqueado por ubicación Mocked.")
        emit('error', {'message': 'Ubicación rechazada: Se detectó el uso de aplicación de GPS falso (Mock Location).'})
        return

    driver_id = client_info['user_id']
    truck = TowTruck.query.filter_by(driver_id=driver_id).first()
    if not truck:
        emit('error', {'message': 'No tienes una grúa registrada.'})
        return

    # Validar que el chofer no intente suplantar otra unidad de grúa
    claimed_truck_id = data.get('truck_id') if isinstance(data, dict) else None
    if claimed_truck_id is not None and int(claimed_truck_id) != truck.id:
        logger.warning(
            f"🚨 [SECURITY ALERT - IDOR/SPOOF] Conductor {driver_id} (Grúa {truck.id}) "
            f"intentó emitir coordenadas para la grúa {claimed_truck_id}."
        )
        emit('error', {'message': 'Violación de seguridad: No puedes emitir telemetría para otra unidad.'})
        return

    lat = data.get('lat') if isinstance(data, dict) else None
    lng = data.get('lng') if isinstance(data, dict) else None

    if lat is None or lng is None:
        emit('error', {'message': 'Coordenadas requeridas.'})
        return

    try:
        lat = float(lat)
        lng = float(lng)

        # Estado previo para validación cinemática Anti-Spoofing (Hallazgo E)
        cached = _truck_telemetry_cache.get(truck.id)
        prev_lat = cached['lat'] if cached else truck.current_lat
        prev_lng = cached['lng'] if cached else truck.current_lng
        prev_time = cached['timestamp'] if cached else truck.last_heartbeat

        is_dev_sim = bool(data.get('is_dev_sim', False)) and current_app.config.get('DEBUG', False)
        if not is_dev_sim:
            is_valid_move, speed_kmh, reason = GeoService.validate_kinematic_movement(
                prev_lat=prev_lat,
                prev_lng=prev_lng,
                prev_timestamp=prev_time,
                new_lat=lat,
                new_lng=lng,
                new_timestamp=now
            )
            if not is_valid_move:
                emit('error', {'message': reason, 'code': 'GPS_SPOOFING_DETECTED', 'speed_kmh': speed_kmh})
                return

        # Coalescing / Throttling de escrituras en Base de Datos (Hallazgo B)
        write_interval_sec = int(current_app.config.get('TELEMETRY_DB_WRITE_INTERVAL_SEC', 10))
        should_persist_db = False

        if not cached or is_dev_sim:
            should_persist_db = True
        else:
            seconds_since_commit = (now - cached['last_db_commit']).total_seconds()
            dist_since_commit_km = GeoService.calculate_distance_km(
                (cached['lat'], cached['lng']), (lat, lng)
            )
            if seconds_since_commit >= write_interval_sec or dist_since_commit_km >= 0.05:
                should_persist_db = True

        last_commit_ts = cached['last_db_commit'] if cached else now
        if should_persist_db:
            truck.update_position(lat, lng)
            db.session.commit()
            last_commit_ts = now

        _truck_telemetry_cache[truck.id] = {
            'lat': lat,
            'lng': lng,
            'timestamp': now,
            'last_db_commit': last_commit_ts
        }

        # Verificar si la grúa tiene un servicio activo para notificar al cliente en su sala privada
        active_request = TowRequest.query.filter(
            TowRequest.truck_id == truck.id,
            TowRequest.status.in_([
                TowRequestStatus.ASSIGNED,
                TowRequestStatus.IN_TRANSIT_TO_USER,
                TowRequestStatus.ARRIVED_AT_USER,
                TowRequestStatus.IN_TRANSIT_TO_DEST
            ])
        ).first()

        if active_request:
            target_point = (
                (active_request.dest_lat, active_request.dest_lng)
                if active_request.status == TowRequestStatus.IN_TRANSIT_TO_DEST and active_request.dest_lat
                else (active_request.origin_lat, active_request.origin_lng)
            )
            dist_remaining = GeoService.calculate_distance_km((lat, lng), target_point)

            socketio.emit('truck_live_location', {
                'request_id': active_request.id,
                'truck_id': truck.id,
                'position': {'lat': lat, 'lng': lng},
                'distance_remaining_km': round(dist_remaining, 2),
                'status': active_request.status.value
            }, room=f"user_{active_request.client_id}")

        # Broadcast general de posición para el mapa global de unidades
        socketio.emit('truck_position_broadcast', {
            'truck_id': truck.id,
            'is_available': truck.is_available,
            'is_active': truck.is_active,
            'position': {'lat': lat, 'lng': lng}
        })

    except Exception as e:
        db.session.rollback()
        logger.error(f"Error procesando posición del chofer: {e}")


@socketio.on('driver_update_status')
def handle_status_transition(data):
    """
    Permite al chofer cambiar de estado en su servicio:
    IN_TRANSIT_TO_USER -> ARRIVED_AT_USER -> IN_TRANSIT_TO_DEST -> COMPLETED
    """
    sid = request.sid
    client_info = connected_clients.get(sid)

    if not client_info or client_info.get('role') != 'DRIVER':
        emit('error', {'message': 'No autorizado.'})
        return

    driver_id = client_info['user_id']
    request_id = data.get('request_id')
    new_status_str = data.get('status', '').upper()

    try:
        result = DispatchService.driver_update_trip_status(request_id, driver_id, new_status_str)
        emit('trip_status_acknowledged', result)
    except Exception as e:
        logger.error(f"Error en driver_update_status: {e}")
        emit('error', {'message': str(e)})
