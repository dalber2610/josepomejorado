from datetime import datetime, timedelta, timezone
import secrets
from werkzeug.security import generate_password_hash, check_password_hash
from app.extensions import db


class OtpVerification(db.Model):
    __tablename__ = 'otp_verifications'

    MAX_ATTEMPTS = 3

    id = db.Column(db.Integer, primary_key=True)
    phone_number = db.Column(db.String(25), nullable=False, index=True)
    otp_hash = db.Column(db.String(255), nullable=False)
    purpose = db.Column(db.String(50), default='SOS_LOGIN', nullable=False)
    attempts = db.Column(db.Integer, default=0, nullable=False)
    is_verified = db.Column(db.Boolean, default=False, nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    @classmethod
    def create_otp(cls, phone_number: str, purpose: str = 'SOS_LOGIN', expiry_minutes: int = 5) -> tuple:
        """
        Genera un código OTP criptográficamente seguro de 6 dígitos
        y lo persiste hasheado para máxima seguridad.
        Retorna la tupla (instancia_db, codigo_plano).
        """
        # Invalidar códigos anteriores no usados para el mismo número y propósito
        cls.query.filter_by(phone_number=phone_number, purpose=purpose, is_verified=False).delete()
        
        # Generar 6 dígitos aleatorios seguros con CSPRNG (secrets)
        plain_code = "".join([str(secrets.randbelow(10)) for _ in range(6)])
        code_hash = generate_password_hash(plain_code)
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=expiry_minutes)

        otp_record = cls(
            phone_number=phone_number,
            otp_hash=code_hash,
            purpose=purpose,
            attempts=0,
            is_verified=False,
            expires_at=expires_at
        )
        db.session.add(otp_record)
        db.session.commit()

        return otp_record, plain_code

    def verify(self, code_attempt: str) -> bool:
        """
        Verifica el código ingresado. Implementa protección estricta contra fuerza bruta (Hallazgo D):
        - Máximo 3 intentos permitidos.
        - Al alcanzar el 3er intento fallido, revoca inmediatamente la vigencia del código.
        """
        now = datetime.now(timezone.utc)
        
        # Validar expiración (manejando aware/naive timestamps)
        exp = self.expires_at
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
            
        if now > exp:
            return False

        if self.attempts >= self.MAX_ATTEMPTS or self.is_verified:
            return False

        self.attempts += 1
        
        if check_password_hash(self.otp_hash, code_attempt.strip()):
            self.is_verified = True
            db.session.commit()
            return True

        # Si alcanzó el límite de 3 intentos fallidos, quemar/expirar el OTP de inmediato
        if self.attempts >= self.MAX_ATTEMPTS:
            self.expires_at = now - timedelta(seconds=1)

        db.session.commit()
        return False

    def to_dict(self):
        return {
            'id': self.id,
            'phone_number': self.phone_number,
            'purpose': self.purpose,
            'is_verified': self.is_verified,
            'attempts': self.attempts,
            'expires_at': self.expires_at.isoformat(),
            'created_at': self.created_at.isoformat()
        }
