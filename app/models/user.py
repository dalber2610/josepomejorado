from datetime import datetime, timezone
import enum
from werkzeug.security import generate_password_hash, check_password_hash
from app.extensions import db


class UserRole(str, enum.Enum):
    CLIENT = 'CLIENT'
    DRIVER = 'DRIVER'
    ADMIN = 'ADMIN'


class ReputationLevel(str, enum.Enum):
    BRONCE = 'BRONCE'
    PLATA = 'PLATA'
    ORO = 'ORO'
    GUARDIAN_VIAL = 'GUARDIÁN VIAL'
    LEYENDA_VIAL = 'LEYENDA VIAL'


class User(db.Model):
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    phone_number = db.Column(db.String(25), unique=True, nullable=False, index=True)
    full_name = db.Column(db.String(100), nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.Enum(UserRole), default=UserRole.CLIENT, nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)

    # Fase 5: Gamificación, Puntos y Nivel de Reputación Vial
    points_balance = db.Column(db.Integer, default=0, nullable=False)
    lifetime_points = db.Column(db.Integer, default=0, nullable=False)
    reputation_level = db.Column(db.String(30), default=ReputationLevel.BRONCE.value, nullable=False)

    # Fase 5: Contacto Familiar de Emergencia (Botón SOS Familiar)
    emergency_contact_name = db.Column(db.String(100), nullable=True)
    emergency_contact_phone = db.Column(db.String(25), nullable=True)

    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False
    )

    # Relaciones
    tow_truck = db.relationship('TowTruck', back_populates='driver', uselist=False)
    requests = db.relationship('TowRequest', back_populates='client', foreign_keys='TowRequest.client_id')
    traffic_reports = db.relationship('TrafficReport', back_populates='author')
    point_transactions = db.relationship('PointTransaction', back_populates='user', cascade='all, delete-orphan')
    redemptions = db.relationship('RewardRedemption', back_populates='user', cascade='all, delete-orphan')

    def set_password(self, password: str):
        """Genera hash seguro de la contraseña con salting."""
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        """Verifica la contraseña ingresada contra el hash almacenado."""
        return check_password_hash(self.password_hash, password)

    def recalculate_reputation_level(self) -> str:
        """
        Calcula y actualiza el nivel de reputación según los puntos acumulados históricos.
        Escala:
          - 0 a 99 pts: BRONCE
          - 100 a 299 pts: PLATA
          - 300 a 699 pts: ORO
          - 700 a 1499 pts: GUARDIÁN VIAL
          - 1500+ pts: LEYENDA VIAL
        """
        pts = int(self.lifetime_points or 0)
        if pts >= 1500:
            self.reputation_level = ReputationLevel.LEYENDA_VIAL.value
        elif pts >= 700:
            self.reputation_level = ReputationLevel.GUARDIAN_VIAL.value
        elif pts >= 300:
            self.reputation_level = ReputationLevel.ORO.value
        elif pts >= 100:
            self.reputation_level = ReputationLevel.PLATA.value
        else:
            self.reputation_level = ReputationLevel.BRONCE.value
        return self.reputation_level

    def get_next_level_info(self) -> dict:
        """Retorna el próximo nivel de reputación y los puntos restantes para alcanzarlo."""
        pts = int(self.lifetime_points or 0)
        thresholds = [
            (100, ReputationLevel.PLATA.value),
            (300, ReputationLevel.ORO.value),
            (700, ReputationLevel.GUARDIAN_VIAL.value),
            (1500, ReputationLevel.LEYENDA_VIAL.value),
        ]
        for threshold, level_name in thresholds:
            if pts < threshold:
                return {
                    'next_level': level_name,
                    'points_needed': threshold - pts,
                    'target_threshold': threshold
                }
        return {
            'next_level': 'MÁXIMO NIVEL ALCANZADO',
            'points_needed': 0,
            'target_threshold': 1500
        }

    def to_dict(self):
        return {
            'id': self.id,
            'email': self.email,
            'phone_number': self.phone_number,
            'full_name': self.full_name,
            'role': self.role.value if isinstance(self.role, UserRole) else self.role,
            'is_active': self.is_active,
            'points_balance': int(self.points_balance or 0),
            'lifetime_points': int(self.lifetime_points or 0),
            'reputation_level': self.reputation_level or ReputationLevel.BRONCE.value,
            'next_level_info': self.get_next_level_info(),
            'emergency_contact': {
                'name': self.emergency_contact_name,
                'phone': self.emergency_contact_phone
            },
            'created_at': self.created_at.isoformat() if self.created_at else None
        }
