from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from app.extensions import db, socketio
from app.models.traffic_report import TrafficReport, TrafficReportType
from app.services.gamification_service import GamificationService
from app.api.geo_routes import validate_coordinates
import logging

logger = logging.getLogger(__name__)
traffic_bp = Blueprint('traffic_bp', __name__, url_prefix='/api/traffic')


@traffic_bp.route('/reports', methods=['GET'])
def get_reports():
    """Obtiene los incidentes viales más recientes con sus contadores de validación cruzada."""
    limit = min(int(request.args.get('limit', 50)), 100)
    reports = TrafficReport.query.order_by(TrafficReport.created_at.desc()).limit(limit).all()
    return jsonify({
        'count': len(reports),
        'reports': [r.to_dict() for r in reports]
    }), 200


@traffic_bp.route('/reports', methods=['POST'])
@jwt_required()
def create_report():
    """
    Permite a un usuario autenticado reportar una incidencia vial y le otorga
    automáticamente +25 puntos de reputación en el Club Guardián Vial (Fase 5).
    """
    user_id = int(get_jwt_identity())
    data = request.get_json() or {}

    lat, lng = validate_coordinates(data.get('lat'), data.get('lng'))
    if lat is None or lng is None:
        return jsonify({'error': 'Coordenadas del incidente requeridas.'}), 400

    report_type_str = data.get('type', 'ACCIDENT').upper()
    if report_type_str not in TrafficReportType.__members__:
        return jsonify({'error': 'Tipo de reporte inválido.'}), 400

    description = data.get('description', '').strip()
    if not description or len(description) < 3:
        return jsonify({'error': 'Descripción obligatoria (mínimo 3 caracteres).'}), 400
    if len(description) > 255:
        return jsonify({'error': 'La descripción no puede exceder 255 caracteres.'}), 400

    try:
        report = TrafficReport(
            author_id=user_id,
            lat=lat,
            lng=lng,
            report_type=TrafficReportType[report_type_str],
            description=description,
            confirmations_count=0,
            confirmed_by_user_ids=[]
        )
        db.session.add(report)
        db.session.flush()

        # Otorgar puntos por reportar incidencia a la comunidad (+25 pts)
        points_info = GamificationService.award_points(
            user_id=user_id,
            points=GamificationService.POINTS_CREATE_REPORT,
            reason_code='TRAFFIC_REPORT_CREATED',
            description=f"Reporte comunitario de tráfico ({report_type_str}): {description[:50]}",
            reference_id=str(report.id),
            auto_commit=False
        )
        db.session.commit()

        report_dict = report.to_dict()
        # Emitir reporte en tiempo real a todos los usuarios conectados
        socketio.emit('new_traffic_report', report_dict)

        return jsonify({
            'message': f'Incidente vial reportado con éxito (+{GamificationService.POINTS_CREATE_REPORT} pts ganados).',
            'report': report_dict,
            'gamification': points_info
        }), 201
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error creando reporte de tráfico: {e}")
        return jsonify({'error': 'Error guardando el reporte de tráfico.'}), 500


@traffic_bp.route('/reports/<int:report_id>/confirm', methods=['POST'])
@jwt_required()
def confirm_report(report_id: int):
    """
    Validación Cruzada de Tráfico (Fase 5):
    Permite a otros conductores confirmar que un incidente vial continúa activo,
    otorgando puntos tanto al validador (+10 pts) como al autor del reporte (+15 pts).
    """
    user_id = int(get_jwt_identity())
    try:
        result = GamificationService.confirm_traffic_report(
            report_id=report_id,
            validator_user_id=user_id
        )
        return jsonify(result), 200
    except ValueError as ve:
        return jsonify({'error': str(ve)}), 400
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error en validación cruzada de tráfico: {e}")
        return jsonify({'error': 'No se pudo procesar la confirmación del reporte.'}), 500
