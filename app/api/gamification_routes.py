from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from app.extensions import db
from app.models.user import User
from app.models.reward import PartnerReward
from app.services.gamification_service import GamificationService
from app.services.notification_service import NotificationService
from app.api.geo_routes import validate_coordinates
import logging

logger = logging.getLogger(__name__)
gamification_bp = Blueprint('gamification_bp', __name__, url_prefix='/api/gamification')


@gamification_bp.route('/profile', methods=['GET'])
@jwt_required()
def get_my_gamification_profile():
    """Retorna el saldo de puntos, nivel de reputación, historial y cupones del usuario autenticado."""
    user_id = int(get_jwt_identity())
    try:
        profile = GamificationService.get_user_gamification_profile(user_id)
        return jsonify(profile), 200
    except ValueError as ve:
        return jsonify({'error': str(ve)}), 404
    except Exception as e:
        logger.error(f"Error consultando perfil de gamificación: {e}")
        return jsonify({'error': 'Error obteniendo datos de reputación y puntos.'}), 500


@gamification_bp.route('/rewards', methods=['GET'])
def list_partner_rewards():
    """Lista el catálogo de talleres mecánicos, caucheras y comercios aliados disponibles para canje."""
    try:
        GamificationService.ensure_default_catalog()
        rewards = (
            PartnerReward.query
            .filter_by(is_active=True)
            .order_by(PartnerReward.points_cost.asc())
            .all()
        )
        return jsonify({
            'count': len(rewards),
            'rewards': [r.to_dict() for r in rewards]
        }), 200
    except Exception as e:
        logger.error(f"Error listando catálogo de recompensas: {e}")
        return jsonify({'error': 'No se pudo cargar el catálogo de aliados.'}), 500


@gamification_bp.route('/redeem', methods=['POST'])
@jwt_required()
def redeem_partner_reward():
    """Canjea puntos del usuario por un cupón digital en un comercio/taller aliado."""
    user_id = int(get_jwt_identity())
    data = request.get_json() or {}
    reward_id = data.get('reward_id')

    if not reward_id:
        return jsonify({'error': 'reward_id es obligatorio.'}), 400

    try:
        result = GamificationService.redeem_reward(user_id=user_id, reward_id=int(reward_id))
        return jsonify(result), 201
    except ValueError as ve:
        return jsonify({'error': str(ve)}), 400
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error canjeando recompensa: {e}")
        return jsonify({'error': 'Error interno al procesar el canje de puntos.'}), 500


@gamification_bp.route('/leaderboard', methods=['GET'])
def get_leaderboard():
    """Retorna el Top 10 de Guardianes Viales con mayor puntaje histórico."""
    limit = min(int(request.args.get('limit', 10)), 50)
    ranking = GamificationService.get_leaderboard(limit=limit)
    return jsonify({
        'count': len(ranking),
        'leaderboard': ranking
    }), 200


@gamification_bp.route('/sos/contact', methods=['POST'])
@jwt_required()
def save_emergency_contact():
    """Guarda o actualiza el contacto familiar de emergencia del usuario."""
    user_id = int(get_jwt_identity())
    data = request.get_json() or {}

    name = (data.get('contact_name') or '').strip()
    phone = (data.get('contact_phone') or '').strip().replace(" ", "").replace("-", "")

    if not name or not phone or len(phone) < 10:
        return jsonify({'error': 'Nombre y teléfono válido (+58...) del contacto familiar son obligatorios.'}), 400

    user = db.session.get(User, user_id)
    if not user:
        return jsonify({'error': 'Usuario no encontrado.'}), 404

    user.emergency_contact_name = name
    user.emergency_contact_phone = phone
    db.session.commit()

    return jsonify({
        'message': 'Contacto familiar de emergencia guardado exitosamente.',
        'emergency_contact': {
            'name': user.emergency_contact_name,
            'phone': user.emergency_contact_phone
        }
    }), 200


@gamification_bp.route('/sos/family-alert', methods=['POST'])
@jwt_required()
def trigger_family_sos():
    """
    Botón SOS Familiar y Alerta por Voz (Fase 5):
    Envía un SMS/WhatsApp inmediato al contacto familiar con las coordenadas GPS exactas
    y un enlace de rastreo satelital en vivo.
    """
    user_id = int(get_jwt_identity())
    data = request.get_json() or {}

    lat, lng = validate_coordinates(data.get('lat'), data.get('lng'))
    if lat is None or lng is None:
        return jsonify({'error': 'Coordenadas GPS válidas son obligatorias para emitir la alerta SOS.'}), 400

    try:
        base_url = request.host_url.rstrip('/')
        alert_data = NotificationService.trigger_family_sos_alert(
            user_id=user_id,
            lat=lat,
            lng=lng,
            contact_name=data.get('contact_name'),
            contact_phone=data.get('contact_phone'),
            custom_message=data.get('custom_message'),
            request_id=data.get('request_id'),
            triggered_via=data.get('triggered_via', 'BUTTON'),
            base_url=base_url
        )
        return jsonify({
            'message': f"🚨 Alerta SOS enviada por SMS/WhatsApp a {alert_data['contact_name']} ({alert_data['contact_phone']}).",
            'alert': alert_data
        }), 201
    except ValueError as ve:
        return jsonify({'error': str(ve)}), 400
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error disparando alerta SOS familiar: {e}")
        return jsonify({'error': 'Error al enviar la alerta SOS familiar.'}), 500


@gamification_bp.route('/sos/track/<tracking_token>', methods=['GET'])
def view_family_sos_tracking(tracking_token: str):
    """
    Endpoint público de rastreo en vivo para el familiar que recibe el enlace por SMS/WhatsApp.
    """
    try:
        snapshot = NotificationService.get_live_tracking_snapshot(tracking_token)
        return jsonify({
            'status': 'active',
            'tracking': snapshot
        }), 200
    except ValueError as ve:
        return jsonify({'error': str(ve)}), 404

