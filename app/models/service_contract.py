from datetime import datetime, timezone
import uuid
import hashlib
from app.extensions import db

class ServiceContract(db.Model):
    __tablename__ = 'service_contracts'

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    request_id = db.Column(db.String(36), db.ForeignKey('tow_requests.id'), unique=True, nullable=False, index=True)
    request = db.relationship('TowRequest', backref=db.backref('contract', uselist=False))

    # Datos de inspección del vehículo remolcado (Protección legal ante reclamos de daños)
    vehicle_plate = db.Column(db.String(20), nullable=False)
    vehicle_model = db.Column(db.String(80), nullable=False)
    vehicle_color = db.Column(db.String(40), nullable=True)
    pre_existing_damages = db.Column(db.Text, default='Sin daños visibles reportados al momento de montar el vehículo.', nullable=False)

    # Auditoría de SLA y Tiempos de Respuesta
    sla_target_minutes = db.Column(db.Integer, default=30, nullable=False) # Meta de llegada al sitio: 30 minutos
    sla_actual_minutes = db.Column(db.Integer, nullable=True)             # Minutos reales transcurridos
    sla_met = db.Column(db.Boolean, default=True, nullable=False)         # ¿Cumplió la meta de tiempo?

    # Firmas digitales de recepción y entrega (Hash criptográfico)
    reception_signature_hash = db.Column(db.String(64), nullable=True)
    delivery_signature_hash = db.Column(db.String(64), nullable=True)
    digital_receipt_token = db.Column(db.String(64), unique=True, nullable=False, default=lambda: uuid.uuid4().hex)

    # Calificación y Reputación Bidireccional
    client_rating = db.Column(db.Integer, nullable=True) # 1 a 5 estrellas
    client_feedback = db.Column(db.String(255), nullable=True)
    driver_rating = db.Column(db.Integer, nullable=True) # 1 a 5 estrellas

    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    delivered_at = db.Column(db.DateTime, nullable=True)

    @staticmethod
    def generate_signature_hash(signer_name: str, doc_id: str, timestamp: datetime) -> str:
        """Genera un hash SHA-256 inmutable que certifica la conformidad digital."""
        raw = f"{signer_name}:{doc_id}:{timestamp.isoformat()}"
        return hashlib.sha256(raw.encode('utf-8')).hexdigest()

    def to_dict(self):
        return {
            'id': self.id,
            'request_id': self.request_id,
            'vehicle': {
                'plate': self.vehicle_plate,
                'model': self.vehicle_model,
                'color': self.vehicle_color,
                'pre_existing_damages': self.pre_existing_damages
            },
            'sla': {
                'target_minutes': self.sla_target_minutes,
                'actual_minutes': self.sla_actual_minutes,
                'sla_met': self.sla_met
            },
            'legal_receipt': {
                'token': self.digital_receipt_token,
                'reception_hash': self.reception_signature_hash,
                'delivery_hash': self.delivery_signature_hash
            },
            'ratings': {
                'client_rating': self.client_rating,
                'client_feedback': self.client_feedback,
                'driver_rating': self.driver_rating
            },
            'created_at': self.created_at.isoformat(),
            'delivered_at': self.delivered_at.isoformat() if self.delivered_at else None
        }

