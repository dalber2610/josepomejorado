from functools import wraps
from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required, get_jwt, get_jwt_identity
from app.extensions import db
from app.models.user import User, UserRole
from app.services.admin_service import AdminService
import logging

logger = logging.getLogger(__name__)
admin_bp = Blueprint('admin_bp', __name__, url_prefix='/api/admin')


def admin_required(fn):
    """
    Decorador de seguridad RBAC (Auditoría #1 - Prevención de Broken Access Control):
    Exige un token JWT válido perteneciente a un usuario con rol ADMIN.
    """
    @wraps(fn)
    @jwt_required()
    def wrapper(*args, **kwargs):
        claims = get_jwt()
        role = claims.get('role')
        if role != UserRole.ADMIN.value:
            user_id = get_jwt_identity()
            user = db.session.get(User, int(user_id)) if user_id and str(user_id).isdigit() else None
            if not user or user.role != UserRole.ADMIN:
                return jsonify({'error': 'Acceso restringido exclusivamente a administradores del Centro de Control.'}), 403
        return fn(*args, **kwargs)
    return wrapper


@admin_bp.route('/kpis', methods=['GET'])
@admin_required
def get_kpis():
    """Retorna los indicadores de operaciones, SLA y financieros en tiempo real."""
    try:
        metrics = AdminService.get_dashboard_kpis()
        return jsonify({'status': 'success', 'data': metrics}), 200
    except Exception as e:
        logger.error(f"Error obteniendo KPIs de administración: {e}")
        return jsonify({'error': 'Error calculando métricas del sistema.'}), 500


@admin_bp.route('/fleet', methods=['GET'])
@admin_required
def get_fleet_live():
    """Retorna la telemetría en vivo de toda la flota de grúas registradas."""
    try:
        fleet = AdminService.get_fleet_telemetry_live()
        return jsonify({'count': len(fleet), 'fleet': fleet}), 200
    except Exception as e:
        logger.error(f"Error consultando flota: {e}")
        return jsonify({'error': 'Error consultando unidades.'}), 500


@admin_bp.route('/operations', methods=['GET'])
@admin_required
def get_recent_operations():
    """Retorna la bitácora de servicios recientes."""
    limit = min(int(request.args.get('limit', 20)), 100)
    try:
        ops = AdminService.get_recent_operations(limit)
        return jsonify({'count': len(ops), 'operations': ops}), 200
    except Exception as e:
        logger.error(f"Error consultando operaciones: {e}")
        return jsonify({'error': 'Error consultando operaciones recientes.'}), 500
