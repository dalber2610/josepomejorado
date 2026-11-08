from flask import Blueprint, jsonify, request
from app.services.currency_service import CurrencyService
from app.models.exchange_rate import ExchangeRateLog
from datetime import datetime, timezone

currency_bp = Blueprint('currency_bp', __name__, url_prefix='/api/currency')


@currency_bp.route('/rate', methods=['GET'])
def get_rate():
    """Consulta la tasa de cambio vigente, su procedencia y el estado del cronjob."""
    rate = CurrencyService.get_current_bcv_rate()
    latest_log = ExchangeRateLog.query.order_by(ExchangeRateLog.fetched_at.desc()).first()
    return jsonify({
        'status': 'success',
        'rate': float(rate),
        'rate_decimal': str(rate),
        'currency': 'VES/USD',
        'source': latest_log.source if latest_log else 'BCV',
        'updated_at': latest_log.fetched_at.isoformat() if latest_log else datetime.now(timezone.utc).isoformat(),
        'cron_status': CurrencyService.get_cron_status()
    }), 200


@currency_bp.route('/sync', methods=['POST'])
def sync_rate_now():
    """
    Dispara manualmente o vía webhook/cron una sincronización inmediata de la tasa oficial BCV.
    """
    data = request.get_json(silent=True) or {}
    custom_rate = data.get('custom_rate')
    source_tag = data.get('source', 'BCV_CRON_MANUAL')

    result = CurrencyService.sync_official_bcv_rate(
        force=True,
        custom_rate=custom_rate,
        source_tag=source_tag
    )
    return jsonify({
        'status': 'synced',
        'message': 'Tasa oficial BCV sincronizada exitosamente.',
        'sync': result
    }), 200


@currency_bp.route('/cron-status', methods=['GET'])
def get_cron_status():
    """Retorna el estado operativo del cronjob de automatización cambiaria."""
    history = ExchangeRateLog.query.order_by(ExchangeRateLog.fetched_at.desc()).limit(5).all()
    return jsonify({
        'cron': CurrencyService.get_cron_status(),
        'recent_logs': [item.to_dict() for item in history]
    }), 200
