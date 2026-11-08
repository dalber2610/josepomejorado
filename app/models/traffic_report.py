from datetime import datetime, timezone
import enum
from app.extensions import db


class TrafficReportType(str, enum.Enum):
    ACCIDENT = 'ACCIDENT'
    ROADBLOCK = 'ROADBLOCK'
    POLICE = 'POLICE'
    HEAVY_TRAFFIC = 'HEAVY_TRAFFIC'
    HAZARD = 'HAZARD'


class TrafficReport(db.Model):
    __tablename__ = 'traffic_reports'

    # Umbral de confirmaciones comunitarias para marcar un reporte como Verificado
    VERIFICATION_THRESHOLD = 2

    id = db.Column(db.Integer, primary_key=True)
    author_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    author = db.relationship('User', back_populates='traffic_reports')

    lat = db.Column(db.Float, nullable=False)
    lng = db.Column(db.Float, nullable=False)
    report_type = db.Column(db.Enum(TrafficReportType), default=TrafficReportType.ACCIDENT, nullable=False)
    description = db.Column(db.String(255), nullable=False)

    # Fase 5: Validación Cruzada Comunitaria
    is_verified = db.Column(db.Boolean, default=False, nullable=False)
    confirmations_count = db.Column(db.Integer, default=0, nullable=False)
    confirmed_by_user_ids = db.Column(db.JSON, default=list, nullable=False)

    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    def has_user_confirmed(self, user_id: int) -> bool:
        """Verifica si un usuario ya confirmó este reporte."""
        confirmed_list = self.confirmed_by_user_ids or []
        return int(user_id) in [int(uid) for uid in confirmed_list]

    def to_dict(self):
        return {
            'id': self.id,
            'author_id': self.author_id,
            'author_name': self.author.full_name if self.author else 'Anónimo',
            'author_reputation': self.author.reputation_level if self.author else 'BRONCE',
            'position': {
                'lat': self.lat,
                'lng': self.lng
            },
            'type': self.report_type.value if isinstance(self.report_type, TrafficReportType) else self.report_type,
            'description': self.description,
            'is_verified': self.is_verified,
            'confirmations_count': int(self.confirmations_count or 0),
            'confirmed_by_user_ids': list(self.confirmed_by_user_ids or []),
            'created_at': self.created_at.isoformat() if self.created_at else None
        }
