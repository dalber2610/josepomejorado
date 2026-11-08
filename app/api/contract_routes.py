from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from app.services.contract_service import ContractService
from app.models.service_contract import ServiceContract
import logging

logger = logging.getLogger(__name__)
contract_bp = Blueprint('contract_bp', __name__, url_prefix='/api/contracts')

@contract_bp.route('/inspect', methods=['POST'])
@jwt_required()
def register_inspection():
    """
    Registra el acta de inspección del vehículo y los daños preexistentes al hacer contacto en el sitio.
    Calcula de inmediato el cumplimiento del SLA de respuesta.
    """
    driver_id = int(get_jwt_identity())
    data = request.get_json() or {}

    request_id = data.get('request_id')
    plate = data.get('vehicle_plate')
    model = data.get('vehicle_model')
    color = data.get('vehicle_color')
    damages = data.get('pre_existing_damages')

    if not request_id or not plate or not model:
        return jsonify({'error': 'request_id, vehicle_plate y vehicle_model son obligatorios.'}), 400

    try:
        contract = ContractService.register_vehicle_inspection(
            request_id=request_id,
            driver_id=driver_id,
            vehicle_plate=plate,
            vehicle_model=model,
            vehicle_color=color,
            pre_existing_damages=damages
        )
        return jsonify({
            'message': 'Acta de inspección y SLA registrados con éxito.',
            'contract': contract.to_dict()
        }), 201
    except PermissionError as pe:
        return jsonify({'error': str(pe)}), 403
    except ValueError as ve:
        return jsonify({'error': str(ve)}), 400
    except Exception as e:
        logger.error(f"Error registrando inspección: {e}")
        return jsonify({'error': 'Error interno al registrar la inspección.'}), 500

@contract_bp.route('/rate', methods=['POST'])
@jwt_required()
def client_sign_and_rate():
    """
    El cliente emite su firma digital de conformidad y califica el servicio (1 a 5 estrellas).
    """
    client_id = int(get_jwt_identity())
    data = request.get_json() or {}

    request_id = data.get('request_id')
    rating = data.get('rating')
    feedback = data.get('feedback', '')

    if not request_id or rating is None:
        return jsonify({'error': 'request_id y rating (1-5) son obligatorios.'}), 400

    try:
        contract = ContractService.client_sign_and_rate(
            request_id=request_id,
            client_id=client_id,
            rating=int(rating),
            feedback=feedback
        )
        return jsonify({
            'message': 'Servicio calificado y conformidad sellada digitalmente.',
            'contract': contract.to_dict()
        }), 200
    except (ValueError, PermissionError) as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        logger.error(f"Error calificando servicio: {e}")
        return jsonify({'error': 'Error guardando calificación.'}), 500

@contract_bp.route('/<request_id>', methods=['GET'])
@jwt_required()
def get_contract_details(request_id):
    """Obtiene los detalles del acta de remolque para las partes involucradas."""
    contract = ServiceContract.query.filter_by(request_id=request_id).first()
    if not contract:
        return jsonify({'contract': None, 'message': 'Aún no se ha generado acta de inspección.'}), 200
    return jsonify({'contract': contract.to_dict()}), 200

@contract_bp.route('/verify/<token>', methods=['GET'])
def verify_receipt_public(token):
    """
    Endpoint público de verificación para compañías de seguros, talleres o autoridades viales.
    Certifica la autenticidad e inmutabilidad del servicio de remolque prestado.
    """
    certified_data = ContractService.get_contract_by_token(token)
    if not certified_data:
        return jsonify({'error': 'El comprobante o token de certificación no existe o es inválido.'}), 404
    return jsonify(certified_data), 200

