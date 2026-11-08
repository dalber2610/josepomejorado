from datetime import datetime, timezone, timedelta
import enum
import uuid
import secrets
from app.extensions import db


class RewardCategory(str, enum.Enum):
    MECANICA = 'MECANICA'
    CAUCHOS = 'CAUCHOS'
    BATERIAS = 'BATERIAS'
    LUBRICANTES = 'LUBRICANTES'
    DESCUENTO_GRUA = 'DESCUENTO_GRUA'


class RedemptionStatus(str, enum.Enum):
    ACTIVE = 'ACTIVE'
    USED = 'USED'
    EXPIRED = 'EXPIRED'


class PartnerReward(db.Model):
    """
    Catálogo de Talleres Mecánicos, Caucheras y Comercios Aliados para canje de puntos.
    """
    __tablename__ = 'partner_rewards'

    id = db.Column(db.Integer, primary_key=True)
    partner_name = db.Column(db.String(120), nullable=False)
    category = db.Column(db.Enum(RewardCategory), default=RewardCategory.MECANICA, nullable=False)
    title = db.Column(db.String(140), nullable=False)
    description = db.Column(db.String(255), nullable=False)
    points_cost = db.Column(db.Integer, nullable=False)
    discount_percentage = db.Column(db.Integer, default=15, nullable=False)
    city_location = db.Column(db.String(80), default='Nacional / Red Aliada', nullable=False)
    stock = db.Column(db.Integer, default=100, nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    redemptions = db.relationship('RewardRedemption', back_populates='reward')

    def to_dict(self):
        return {
            'id': self.id,
            'partner_name': self.partner_name,
            'category': self.category.value if isinstance(self.category, RewardCategory) else self.category,
            'title': self.title,
            'description': self.description,
            'points_cost': int(self.points_cost),
            'discount_percentage': int(self.discount_percentage),
            'city_location': self.city_location,
            'stock': int(self.stock),
            'is_active': self.is_active
        }


class PointTransaction(db.Model):
    """
    Bitácora inmutable de movimientos de puntos (ganados por reportes/validaciones o gastados en canjes).
    """
    __tablename__ = 'point_transactions'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    user = db.relationship('User', back_populates='point_transactions')

    points_delta = db.Column(db.Integer, nullable=False)  # Positivo (+) ganancia, Negativo (-) canje
    reason_code = db.Column(db.String(50), nullable=False)
    description = db.Column(db.String(255), nullable=False)
    reference_id = db.Column(db.String(64), nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'points_delta': int(self.points_delta),
            'reason_code': self.reason_code,
            'description': self.description,
            'reference_id': self.reference_id,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }


class RewardRedemption(db.Model):
    """
    Cupón digital emitido cuando un usuario canjea sus puntos en un Taller o Comercio Aliado.
    """
    __tablename__ = 'reward_redemptions'

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    reward_id = db.Column(db.Integer, db.ForeignKey('partner_rewards.id'), nullable=False, index=True)

    user = db.relationship('User', back_populates='redemptions')
    reward = db.relationship('PartnerReward', back_populates='redemptions')

    points_spent = db.Column(db.Integer, nullable=False)
    coupon_code = db.Column(db.String(32), unique=True, nullable=False, index=True)
    status = db.Column(db.Enum(RedemptionStatus), default=RedemptionStatus.ACTIVE, nullable=False)

    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    expires_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc) + timedelta(days=30),
        nullable=False
    )

    @staticmethod
    def generate_coupon_code(prefix: str = 'JOSEPO') -> str:
        """Genera un código alfanumérico único para presentar en el taller aliado."""
        token = secrets.token_hex(3).upper()
        return f"{prefix}-{token}"

    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'reward_id': self.reward_id,
            'partner_name': self.reward.partner_name if self.reward else 'Comercio Aliado',
            'reward_title': self.reward.title if self.reward else 'Beneficio Vial',
            'discount_percentage': self.reward.discount_percentage if self.reward else 0,
            'points_spent': int(self.points_spent),
            'coupon_code': self.coupon_code,
            'status': self.status.value if isinstance(self.status, RedemptionStatus) else self.status,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'expires_at': self.expires_at.isoformat() if self.expires_at else None
        }


class FamilySosAlert(db.Model):
    """
    Registro de Alertas de Emergencia SOS Familiar enviadas por SMS/WhatsApp
    con enlace de rastreo satelital en vivo.
    """
    __tablename__ = 'family_sos_alerts'

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    request_id = db.Column(db.String(36), db.ForeignKey('tow_requests.id'), nullable=True)

    user = db.relationship('User')
    tow_request = db.relationship('TowRequest')

    contact_name = db.Column(db.String(100), nullable=False)
    contact_phone = db.Column(db.String(25), nullable=False)
    lat = db.Column(db.Float, nullable=False)
    lng = db.Column(db.Float, nullable=False)
    custom_message = db.Column(db.String(255), nullable=True)
    triggered_via = db.Column(db.String(20), default='BUTTON', nullable=False)  # BUTTON | VOICE_COMMAND
    tracking_token = db.Column(
        db.String(48),
        unique=True,
        nullable=False,
        index=True,
        default=lambda: secrets.token_urlsafe(18)
    )
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'user_name': self.user.full_name if self.user else 'Conductor Josepo',
            'user_phone': self.user.phone_number if self.user else None,
            'request_id': self.request_id,
            'contact_name': self.contact_name,
            'contact_phone': self.contact_phone,
            'position': {
                'lat': self.lat,
                'lng': self.lng
            },
            'google_maps_url': f"https://www.google.com/maps?q={self.lat},{self.lng}",
            'tracking_token': self.tracking_token,
            'tracking_url': f"/api/gamification/sos/track/{self.tracking_token}",
            'custom_message': self.custom_message,
            'triggered_via': self.triggered_via,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }

