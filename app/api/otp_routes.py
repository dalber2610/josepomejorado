from flask import Blueprint, request, jsonify
from app.extensions import limiter, get_client_ip
from app.services.otp_service import OtpService
from app.utils.rate_limiter import otp_rate_limiter
from app.utils.schema_validator import validate_json_schema
import logging

logger = logging.getLogger(__name__)
otp_bp = Blueprint('otp_bp', __name__, url_prefix='/api/auth/otp')

OTP_SEND_SCHEMA = {
    'phone_number': {
        'type': 'str',
        'required': True,
        'min_length': 7,
        'max_length': 25,
        'required_error': 'Número de teléfono requerido.',
    },
    'purpose': {
        'type': 'str',
        'required': False,
        'max_length': 40,
    },
    'channel': {
        'type': 'str',
        'required': False,
        'max_length': 20,
    },
}

OTP_VERIFY_SCHEMA = {
    'phone_number': {
        'type': 'str',
        'required': True,
        'min_length': 7,
        'max_length': 25,
        'required_error': 'Número de teléfono y código OTP son obligatorios.',
    },
    'code': {
        'type': 'str',
        'required': False,  # Soportamos también 'otp_code' por compatibilidad móvil
    },
    'otp_code': {
        'type': 'str',
        'required': False,
    },
    'purpose': {
        'type': 'str',
        'required': False,
        'max_length': 40,
    },
    'full_name': {
        'type': 'str',
        'required': False,
        'max_length': 120,
    },
}


@otp_bp.route('/send', methods=['POST'])
@otp_bp.route('/request', methods=['POST'])
@limiter.limit("5 per 5 minutes")
@validate_json_schema(OTP_SEND_SCHEMA)
def send_otp():
    """
    Solicita el envío de un código de verificación SMS / WhatsApp (6 dígitos).
    Protegido con Flask-Limiter + Rate Limiting por IP y por teléfono (Hallazgo D & Fase 7).
    """
    data = request.get_json() or {}
    phone_number = data.get('phone_number', '').strip()
    purpose = data.get('purpose', 'SOS_LOGIN').strip()

    client_ip = get_client_ip()
    clean_phone = phone_number.replace(" ", "").replace("-", "")

    # 1. Rate Limit por IP (máx 5 solicitudes de envío cada 5 minutos)
    allowed_ip, retry_ip = otp_rate_limiter.is_allowed(f"otp_send_ip:{client_ip}", max_requests=5, window_seconds=300)
    if not allowed_ip:
        logger.warning(f"🚨 [RATE LIMIT OTP SEND] IP {client_ip} bloqueada temporalmente.")
        return jsonify({
            'error': f'Demasiadas solicitudes de código desde tu dirección IP. Intenta de nuevo en {retry_ip} segundos.',
            'retry_after_seconds': retry_ip
        }), 429

    # 2. Rate Limit por Teléfono (máx 3 códigos cada 5 minutos)
    allowed_phone, retry_phone = otp_rate_limiter.is_allowed(f"otp_send_phone:{clean_phone}", max_requests=3, window_seconds=300)
    if not allowed_phone:
        logger.warning(f"🚨 [RATE LIMIT OTP SEND] Teléfono {clean_phone} excedió límite de envíos.")
        return jsonify({
            'error': f'Has solicitado demasiados códigos para este número. Espera {retry_phone} segundos.',
            'retry_after_seconds': retry_phone
        }), 429

    try:
        result = OtpService.request_otp(phone_number, purpose)
        return jsonify(result), 200
    except ValueError as ve:
        return jsonify({'error': str(ve)}), 400
    except Exception as e:
        logger.error(f"Error enviando OTP: {e}")
        return jsonify({'error': 'Error de comunicación al enviar el código de verificación.'}), 500


@otp_bp.route('/verify', methods=['POST'])
@limiter.limit("6 per 5 minutes")
@validate_json_schema(OTP_VERIFY_SCHEMA)
def verify_otp():
    """
    Verifica el código OTP y entrega un Token JWT de sesión inmediatamente.
    Protegido contra ataques de fuerza bruta mediante Flask-Limiter + límite de 3 intentos (Hallazgo D & Fase 7).
    """
    data = request.get_json() or {}
    phone_number = data.get('phone_number', '').strip()
    code = (data.get('code') or data.get('otp_code') or '').strip()
    purpose = data.get('purpose', 'SOS_LOGIN').strip()
    full_name = data.get('full_name', '').strip()

    if not phone_number or not code:
        return jsonify({'error': 'Número de teléfono y código OTP son obligatorios.'}), 400

    client_ip = get_client_ip()
    # Rate Limit por IP en verificación (máx 6 intentos cada 5 minutos por IP)
    allowed_ip, retry_ip = otp_rate_limiter.is_allowed(f"otp_verify_ip:{client_ip}", max_requests=6, window_seconds=300)
    if not allowed_ip:
        logger.warning(f"🚨 [RATE LIMIT OTP VERIFY] Posible ataque de fuerza bruta desde IP {client_ip}.")
        return jsonify({
            'error': f'Demasiados intentos de verificación desde tu IP. Bloqueado por {retry_ip} segundos.',
            'retry_after_seconds': retry_ip
        }), 429

    if len(code) != 6 or not code.isdigit():
        return jsonify({'error': 'El código OTP debe tener 6 dígitos numéricos.'}), 400

    try:
        result = OtpService.verify_otp_and_login(phone_number, code, purpose, full_name)
        return jsonify(result), 200
    except ValueError as ve:
        return jsonify({'error': str(ve)}), 400
    except Exception as e:
        logger.error(f"Error verificando OTP: {e}")
        return jsonify({'error': 'Error interno al verificar el código.'}), 500
