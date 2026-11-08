from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from app.services.dispatch_service import DispatchService
from app.models.tow_truck import TowTruck
from app.models.tow_request import TowRequest, TowRequestStatus
from app.api.geo_routes import validate_coordinates
import logging

logger = logging.getLogger(__name__)
tow_bp = Blueprint('tow_bp', __name__, url_prefix='/api/tows')

@tow_bp.route('/available-trucks', methods=['GET'])
def get_available_trucks():
    """Retorna las grúas activas y disponibles para mostrarlas en el mapa del usuario."""
    trucks = TowTruck.query.filter_by(is_available=True, is_active=True).all()
    return jsonify({
        'count': len(trucks),
        'trucks': [t.to_dict() for t in trucks]
    }), 200

@tow_bp.route('/estimate', methods=['POST'])
def estimate_cost():
    """Permite al cliente obtener un estimado de costos y tiempo antes de solicitar."""
    data = request.get_json() or {}
    origin = data.get('origin', {})
    dest = data.get('destination')

    orig_lat, orig_lng = validate_coordinates(origin.get('lat'), origin.get('lng'))
    if orig_lat is None or orig_lng is None:
        return jsonify({'error': 'Coordenadas de origen obligatorias y válidas.'}), 400

    dest_lat, dest_lng = None, None
    if dest:
        dest_lat, dest_lng = validate_coordinates(dest.get('lat'), dest.get('lng'))
        if dest_lat is None or dest_lng is None:
            return jsonify({'error': 'Coordenadas de destino inválidas.'}), 400

    try:
        estimate = DispatchService.estimate_service(orig_lat, orig_lng, dest_lat, dest_lng)
        return jsonify(estimate), 200
    except Exception as e:
        logger.error(f"Error generando estimación: {e}")
        return jsonify({'error': 'No se pudo generar la estimación de servicio.'}), 500

@tow_bp.route('/request', methods=['POST'])
@jwt_required()
def request_tow():
    """Solicita una grúa de forma oficial y atómica con control de concurrencia."""
    user_id = int(get_jwt_identity())
    data = request.get_json() or {}

    origin = data.get('origin', {})
    dest = data.get('destination')
    request_id = data.get('request_id') # UUID generado en cliente para idempotencia

    orig_lat, orig_lng = validate_coordinates(origin.get('lat'), origin.get('lng'))
    if orig_lat is None or orig_lng is None:
        return jsonify({'error': 'Coordenadas de origen requeridas.'}), 400

    dest_lat, dest_lng = None, None
    if dest:
        dest_lat, dest_lng = validate_coordinates(dest.get('lat'), dest.get('lng'))
        if dest_lat is None or dest_lng is None:
            return jsonify({'error': 'Coordenadas de destino inválidas.'}), 400

    try:
        tow_request = DispatchService.request_tow_with_offer(
            client_id=user_id,
            origin_lat=orig_lat,
            origin_lng=orig_lng,
            dest_lat=dest_lat,
            dest_lng=dest_lng,
            request_id=request_id
        )
        return jsonify({
            'message': 'Buscando y contactando a la grúa más cercana...',
            'request': tow_request.to_dict()
        }), 201

    except ValueError as ve:
        return jsonify({'error': str(ve)}), 400
    except RuntimeError as re:
        return jsonify({'error': str(re)}), 503
    except Exception as e:
        logger.error(f"Error en request_tow: {e}")
        return jsonify({'error': 'Ocurrió un error inesperado al procesar su solicitud.'}), 500

@tow_bp.route('/active', methods=['GET'])
@jwt_required()
def get_active_tow():
    """Obtiene el servicio en curso del usuario actual."""
    user_id = int(get_jwt_identity())
    active_req = TowRequest.query.filter(
        TowRequest.client_id == user_id,
        TowRequest.status.notin_([TowRequestStatus.COMPLETED, TowRequestStatus.CANCELLED])
    ).first()

    if not active_req:
        return jsonify({'active_request': None}), 200

    return jsonify({'active_request': active_req.to_dict()}), 200

@tow_bp.route('/<request_id>', methods=['GET'])
@jwt_required()
def get_tow_detail(request_id):
    """Obtiene detalles específicos de una solicitud."""
    user_id = int(get_jwt_identity())
    req = TowRequest.query.filter_by(id=request_id).first()
    if not req:
        return jsonify({'error': 'Solicitud no encontrada.'}), 404

    # Solo el cliente solicitante o el chofer asignado pueden verla
    if req.client_id != user_id and (req.assigned_truck and req.assigned_truck.driver_id != user_id):
        return jsonify({'error': 'Acceso no autorizado a este servicio.'}), 403

    return jsonify({'request': req.to_dict()}), 200

@tow_bp.route('/<request_id>/cancel', methods=['POST'])
@jwt_required()
def cancel_tow(request_id):
    """Cancela una solicitud de grúa en curso."""
    user_id = int(get_jwt_identity())
    try:
        cancelled = DispatchService.cancel_request(request_id, user_id)
        return jsonify({
            'message': 'Servicio cancelado exitosamente.',
            'request': cancelled.to_dict()
        }), 200
    except ValueError as ve:
        return jsonify({'error': str(ve)}), 400
    except PermissionError as pe:
        return jsonify({'error': str(pe)}), 403
    except Exception as e:
        logger.error(f"Error cancelando servicio: {e}")
        return jsonify({'error': 'No se pudo cancelar el servicio.'}), 500
