from datetime import datetime, timezone
from app.extensions import db

class TowTruck(db.Model):
    __tablename__ = 'tow_trucks'

    id = db.Column(db.Integer, primary_key=True)
    license_plate = db.Column(db.String(20), unique=True, nullable=False, index=True)
    brand_model = db.Column(db.String(80), nullable=False)
    
    # Vinculación obligatoria con un chofer registrado
    driver_id = db.Column(db.Integer, db.ForeignKey('users.id'), unique=True, nullable=True)
    driver = db.relationship('User', back_populates='tow_truck')
    
    # Telemetría en tiempo real
    current_lat = db.Column(db.Float, nullable=False)
    current_lng = db.Column(db.Float, nullable=False)
    is_available = db.Column(db.Boolean, default=True, index=True, nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False) # Turno activo (Online / Offline)
    last_heartbeat = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)

    # Relación con solicitudes de servicio
    assigned_requests = db.relationship('TowRequest', back_populates='assigned_truck', foreign_keys='TowRequest.truck_id')

    def update_position(self, lat: float, lng: float):
        """Actualiza la telemetría GPS del vehículo."""
        self.current_lat = lat
        self.current_lng = lng
        self.last_heartbeat = datetime.now(timezone.utc)

    def to_dict(self):
        return {
            'id': self.id,
            'license_plate': self.license_plate,
            'brand_model': self.brand_model,
            'driver_id': self.driver_id,
            'driver_name': self.driver.full_name if self.driver else None,
            'driver_phone': self.driver.phone_number if self.driver else None,
            'current_position': {
                'lat': self.current_lat,
                'lng': self.current_lng
            },
            'is_available': self.is_available,
            'is_active': self.is_active,
            'last_heartbeat': self.last_heartbeat.isoformat()
        }
