import hmac
import hashlib
import logging
from flask import Blueprint, request, jsonify, current_app
from flask_jwt_extended import jwt_required, get_jwt_identity
from app.services.payment_service import PaymentService
from app.models.payment import Payment

logger = logging.getLogger(__name__)
payment_bp = Blueprint('payment_bp', __name__, url_prefix='/api/payments')

# Campos financieros prohibidos en el payload del cliente (Hallazgo C: Anti-Parameter Tampering)
FORBIDDEN_CLIENT_PAYMENT_FIELDS = {
    'amount', 'amount_ves', 'amount_usd', 'amount_ves_cents', 'amount_usd_cents',
    'cost_ves', 'cost_usd', 'cost_ves_cents', 'cost_usd_cents',
    'exchange_rate', 'rate', 'driver_payout', 'driver_payout_cents',
    'platform_fee', 'platform_fee_cents'
}


@payment_bp.route('/banks', methods=['GET'])
def get_supported_banks():
    """Retorna la lista de bancos habilitados para Pago Móvil en Venezuela."""
    banks = PaymentService.get_supported_banks()
    return jsonify({
        'count': len(banks),
        'banks': banks
    }), 200


@payment_bp.route('/pago-movil/escrow', methods=['POST'])
@jwt_required()
def register_pago_movil():
    """
    Registra el Pago Móvil y congela el importe como Garantía Escrow.
    Mitigación Hallazgo C: Rechaza cualquier intento de enviar montos o tasas de cambio
    desde el navegador; el servidor calcula autoritativamente en base a TowRequest y ExchangeRateLog.
    """
    user_id = int(get_jwt_identity())
    data = request.get_json() or {}

    # Detección activa de Parameter Tampering
    tampered_fields = FORBIDDEN_CLIENT_PAYMENT_FIELDS.intersection(data.keys())
    if tampered_fields:
        logger.warning(
            f"🚨 [SECURITY ALERT - PARAMETER TAMPERING] Usuario {user_id} intentó inyectar "
            f"campos financieros prohibidos en el pago: {tampered_fields}"
        )
        return jsonify({
            'error': 'Manipulación de parámetros financieros detectada. Los montos y tasas de cambio son calculados exclusivamente por el servidor.'
        }), 400

    request_id = data.get('request_id')
    bank_code = data.get('bank_code')
    payer_phone = data.get('payer_phone')
    payer_id_card = data.get('payer_id_card')
    reference_number = data.get('reference_number')

    if not all([request_id, bank_code, payer_phone, payer_id_card, reference_number]):
        return jsonify({
            'error': 'Todos los campos bancarios son obligatorios (request_id, bank_code, payer_phone, payer_id_card, reference_number).'
        }), 400

    try:
        payment = PaymentService.register_pago_movil_escrow(
            client_id=user_id,
            request_id=request_id,
            bank_code=bank_code,
            payer_phone=payer_phone,
            payer_id_card=payer_id_card,
            reference_number=reference_number
        )

        return jsonify({
            'message': 'Garantía de Pago Móvil registrada exitosamente en Escrow.',
            'payment': payment.to_dict()
        }), 201

    except ValueError as ve:
        return jsonify({'error': str(ve)}), 400
    except PermissionError as pe:
        return jsonify({'error': str(pe)}), 403
    except Exception as e:
        logger.error(f"Error registrando pago móvil: {e}")
        return jsonify({'error': 'Error procesando el registro del pago móvil.'}), 500


@payment_bp.route('/request/<request_id>', methods=['GET'])
@jwt_required()
def get_payment_status(request_id):
    """Consulta el estado del pago o garantía de un servicio específico."""
    user_id = int(get_jwt_identity())
    payment = Payment.query.filter_by(request_id=request_id).order_by(Payment.created_at.desc()).first()

    if not payment:
        return jsonify({'payment': None, 'status': 'UNPAID'}), 200

    # Solo el cliente o el conductor asignado pueden ver el pago
    if payment.client_id != user_id and payment.driver_id != user_id:
        return jsonify({'error': 'Acceso no autorizado al comprobante de pago.'}), 403

    return jsonify({'payment': payment.to_dict()}), 200


@payment_bp.route('/webhook', methods=['POST'])
def payment_webhook():
    """
    Webhook para integración con pasarelas automáticas (ej. Biopago, MegaSoft, etc.).
    Protegido con validación criptográfica HMAC-SHA256 en tiempo constante.
    """
    signature_header = request.headers.get('X-Webhook-Signature', '').strip()
    webhook_secret = current_app.config.get('WEBHOOK_SECRET', '')

    raw_body = request.get_data() or b''
    expected_sig = hmac.new(
        webhook_secret.encode('utf-8'),
        raw_body,
        hashlib.sha256
    ).hexdigest()

    if not signature_header or not hmac.compare_digest(signature_header, expected_sig):
        logger.warning("🚨 [SECURITY ALERT] Intento de acceso a /api/payments/webhook con firma HMAC inválida.")
        return jsonify({'error': 'Firma criptográfica de webhook inválida o ausente.'}), 401

    data = request.get_json() or {}
    reference = data.get('reference') or data.get('reference_number')
    status = data.get('status', '').upper()
    reported_amount = data.get('amount_ves_cents')

    if not reference:
        return jsonify({'error': 'Referencia requerida'}), 400

    payment = Payment.query.filter_by(reference_number=reference).first()
    if not payment:
        return jsonify({'status': 'ignored', 'message': 'Referencia no encontrada en la base de datos'}), 404

    if reported_amount is not None and int(reported_amount) != payment.amount_ves_cents:
        logger.warning(
            f"🚨 [SECURITY ALERT - WEBHOOK AMOUNT MISMATCH] Ref #{reference}: "
            f"esperado {payment.amount_ves_cents}, recibido {reported_amount}"
        )
        return jsonify({'error': 'El monto reportado por la pasarela no coincide con el monto oficial de la orden.'}), 400

    logger.info(f"🔔 [WEBHOOK PAGO AUTENTICADO] Referencia #{reference} recibió estado: {status}")

    return jsonify({
        'status': 'received',
        'payment_id': payment.id,
        'current_status': payment.status.value
    }), 200
