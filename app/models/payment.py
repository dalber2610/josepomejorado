from datetime import datetime, timezone
import uuid
import enum
from decimal import Decimal, ROUND_HALF_UP
from app.extensions import db

class PaymentStatus(str, enum.Enum):
    PENDING = 'PENDING'
    HELD_IN_ESCROW = 'HELD_IN_ESCROW'        # Pago retenido como garantía antes del auxilio
    CONFIRMED = 'CONFIRMED'                  # Validado por banco / webhook
    RELEASED_TO_DRIVER = 'RELEASED_TO_DRIVER'# Fondos liberados al chofer al completar
    REFUNDED = 'REFUNDED'                    # Reembolsado al cliente por cancelación
    REJECTED = 'REJECTED'                    # Rechazado por referencia inválida o banco

class PaymentMethod(str, enum.Enum):
    PAGO_MOVIL = 'PAGO_MOVIL'
    TRANSFER = 'TRANSFER'
    CARD_DEBIT = 'CARD_DEBIT'
    CARD_CREDIT = 'CARD_CREDIT'
    CASH = 'CASH'

class Payment(db.Model):
    __tablename__ = 'payments'

    # Identificador único global (Idempotencia financiera)
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))

    # Relación con la solicitud de remolque
    request_id = db.Column(db.String(36), db.ForeignKey('tow_requests.id'), nullable=False, index=True)
    request = db.relationship('TowRequest', back_populates='payments')

    # Actores
    client_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    client = db.relationship('User', foreign_keys=[client_id])

    driver_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True, index=True)
    driver = db.relationship('User', foreign_keys=[driver_id])

    # Montos en CENTAVOS ENTEROS (Regla de negocio: Sin floats para evitar desbordamiento)
    amount_ves_cents = db.Column(db.BigInteger, nullable=False)
    amount_usd_cents = db.Column(db.BigInteger, nullable=False)
    exchange_rate = db.Column(db.Numeric(12, 4), nullable=False)

    # División de ingresos (Split de plataforma)
    driver_payout_cents = db.Column(db.BigInteger, nullable=False) # 85% para el conductor
    platform_fee_cents = db.Column(db.BigInteger, nullable=False)  # 15% para Josepo

    # Método y Estado
    method = db.Column(db.Enum(PaymentMethod), default=PaymentMethod.PAGO_MOVIL, nullable=False)
    status = db.Column(db.Enum(PaymentStatus), default=PaymentStatus.PENDING, nullable=False, index=True)

    # Datos específicos de Pago Móvil / Transferencia bancaria
    reference_number = db.Column(db.String(50), nullable=True, index=True) # Referencia bancaria (4 a 8 dígitos)
    bank_code = db.Column(db.String(10), nullable=True)                     # Ej: '0102', '0134'
    bank_name = db.Column(db.String(80), nullable=True)                     # Ej: 'Banco de Venezuela', 'Banesco'
    payer_phone = db.Column(db.String(25), nullable=True)                   # Teléfono emisor
    payer_id_card = db.Column(db.String(20), nullable=True)                 # Cédula o RIF del pagador (V-12345678)

    # Trazabilidad de Auditoría
    held_at = db.Column(db.DateTime, nullable=True)     # Momento en que se congeló la garantía
    released_at = db.Column(db.DateTime, nullable=True) # Momento en que se acreditó al chofer
    refunded_at = db.Column(db.DateTime, nullable=True) # Momento del reembolso
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)

    @classmethod
    def calculate_split(cls, total_cents: int, driver_percentage: Decimal = Decimal('0.85')) -> tuple:
        """
        Calcula la división de pago de forma exacta en centavos:
        85% para el operador de la grúa y 15% de comisión de servicio para la plataforma.
        """
        total = Decimal(str(total_cents))
        driver_payout = int((total * driver_percentage).quantize(Decimal('1'), rounding=ROUND_HALF_UP))
        platform_fee = total_cents - driver_payout
        return driver_payout, platform_fee

    def to_dict(self):
        return {
            'id': self.id,
            'request_id': self.request_id,
            'client_id': self.client_id,
            'client_name': self.client.full_name if self.client else None,
            'driver_id': self.driver_id,
            'driver_name': self.driver.full_name if self.driver else None,
            'pricing': {
                'amount_ves': round(self.amount_ves_cents / 100.0, 2),
                'amount_usd': round(self.amount_usd_cents / 100.0, 2),
                'amount_ves_cents': self.amount_ves_cents,
                'amount_usd_cents': self.amount_usd_cents,
                'driver_payout_ves': round(self.driver_payout_cents / 100.0, 2),
                'platform_fee_ves': round(self.platform_fee_cents / 100.0, 2),
                'exchange_rate': float(self.exchange_rate)
            },
            'method': self.method.value if isinstance(self.method, PaymentMethod) else self.method,
            'status': self.status.value if isinstance(self.status, PaymentStatus) else self.status,
            'banking_info': {
                'reference_number': self.reference_number,
                'bank_code': self.bank_code,
                'bank_name': self.bank_name,
                'payer_phone': self.payer_phone,
                'payer_id_card': self.payer_id_card
            },
            'timestamps': {
                'created_at': self.created_at.isoformat(),
                'held_at': self.held_at.isoformat() if self.held_at else None,
                'released_at': self.released_at.isoformat() if self.released_at else None,
                'refunded_at': self.refunded_at.isoformat() if self.refunded_at else None
            }
        }

