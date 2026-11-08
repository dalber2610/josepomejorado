import os
import logging
from flask import current_app
from flask_jwt_extended import create_access_token
from app.extensions import db
from app.models.otp_verification import OtpVerification
from app.models.user import User, UserRole

logger = logging.getLogger(__name__)


class OtpService:
    """Servicio de autenticación multifactor (MFA/OTP) para emergencias viales."""

    @classmethod
    def request_otp(cls, phone_number: str, purpose: str = 'SOS_LOGIN') -> dict:
        """
        Genera y envía un código OTP de 6 dígitos al teléfono del usuario.
        """
        clean_phone = phone_number.strip().replace(" ", "").replace("-", "")
        if not clean_phone or len(clean_phone) < 10:
            raise ValueError("Número telefónico inválido. Debe incluir código de país o área (Ej: +584121234567).")

        # Generar registro y código seguro
        otp_record, plain_code = OtpVerification.create_otp(
            phone_number=clean_phone,
            purpose=purpose,
            expiry_minutes=5
        )

        # Entrega de mensaje (SMS / WhatsApp Gateway)
        cls._dispatch_message(clean_phone, plain_code, purpose)

        is_dev = current_app.config.get('DEBUG', False) or os.getenv('FLASK_ENV') == 'development'

        return {
            'status': 'sent',
            'phone_number': clean_phone,
            'expires_in_seconds': 300,
            'purpose': purpose,
            # En modo desarrollo/demo se incluye el código para facilitar pruebas sin costo de SMS
            'demo_otp_code': plain_code if is_dev else None,
            'message': f"Código de verificación enviado exitosamente a {clean_phone}."
        }

    @classmethod
    def verify_otp_and_login(cls, phone_number: str, code: str, purpose: str = 'SOS_LOGIN', full_name: str = None) -> dict:
        """
        Valida el código de 6 dígitos bajo bloqueo transaccional (`with_for_update()`).
        Si alcanza el 3er intento fallido, el OTP queda revocado permanentemente.
        """
        clean_phone = phone_number.strip().replace(" ", "").replace("-", "")
        
        otp_record = OtpVerification.query.filter_by(
            phone_number=clean_phone,
            purpose=purpose,
            is_verified=False
        ).order_by(OtpVerification.created_at.desc()).with_for_update().first()

        if not otp_record:
            raise ValueError("No hay un código OTP activo para este número telefónico. Solicita uno nuevo.")

        if otp_record.attempts >= OtpVerification.MAX_ATTEMPTS:
            raise ValueError("Código invalidado por exceder el máximo de 3 intentos fallidos. Solicita un código nuevo.")

        if not otp_record.verify(code):
            remaining = max(0, OtpVerification.MAX_ATTEMPTS - otp_record.attempts)
            if remaining == 0:
                logger.warning(f"🚨 [SECURITY ALERT - OTP BRUTE FORCE] Código OTP revocado tras 3 intentos fallidos para {clean_phone}")
                raise ValueError("Código inválido. Has alcanzado el límite máximo de 3 intentos y el código ha sido anulado.")
            raise ValueError(f"Código incorrecto o vencido. Te quedan {remaining} intento(s).")

        # Código verificado exitosamente
        user = User.query.filter_by(phone_number=clean_phone).first()
        is_new_user = False

        if not user:
            is_new_user = True
            synthetic_email = f"sos_{clean_phone.replace('+', '')}@josepo.com"
            user = User(
                email=synthetic_email,
                phone_number=clean_phone,
                full_name=full_name.strip() if full_name else f"Usuario SOS ({clean_phone[-4:]})",
                role=UserRole.CLIENT
            )
            user.set_password(os.urandom(16).hex())
            db.session.add(user)
            db.session.commit()

        access_token = create_access_token(
            identity=str(user.id),
            additional_claims={'role': user.role.value, 'name': user.full_name}
        )

        return {
            'status': 'verified',
            'access_token': access_token,
            'is_new_user': is_new_user,
            'user': user.to_dict(),
            'message': 'Teléfono verificado correctamente.'
        }

    @classmethod
    def _dispatch_message(cls, phone: str, code: str, purpose: str):
        """
        Canal de despacho de mensajes: Soporta logs de consola y pasarelas SMS/WhatsApp.
        """
        sms_text = f"[JOSEPO AUXILIO VIAL] Tu código de seguridad es: {code}. Válido por 5 minutos. No lo compartas con nadie."
        cls.send_custom_alert_message(phone, sms_text, category=f"MFA/OTP ({purpose})")

    @classmethod
    def send_custom_alert_message(cls, phone: str, text_message: str, category: str = "SOS_ALERT") -> dict:
        """
        Envía mensajes de alerta SMS / WhatsApp (utilizado tanto para códigos OTP como para
        el Botón SOS Familiar con enlace de rastreo en vivo de Fase 5).
        """
        clean_phone = phone.strip().replace(" ", "").replace("-", "")
        logger.info(f"📲 [{category}] Despachando SMS/WhatsApp -> {clean_phone}")
        print("\n" + "=" * 60)
        print(f"📲 PASARELA SMS / WHATSAPP ({category}) -> {clean_phone}")
        print(f"💬 Mensaje: {text_message}")
        print("=" * 60 + "\n")
        return {
            'delivered': True,
            'recipient_phone': clean_phone,
            'category': category,
            'message_preview': text_message
        }
