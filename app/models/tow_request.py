from datetime import datetime, timezone
import uuid
import enum
from app.extensions import db

class TowRequestStatus(str, enum.Enum):
    PENDING = 'PENDING'
    OFFERED = 'OFFERED'
    ASSIGNED = 'ASSIGNED'
    IN_TRANSIT_TO_USER = 'IN_TRANSIT_TO_USER'
    ARRIVED_AT_USER = 'ARRIVED_AT_USER'
    IN_TRANSIT_TO_DEST = 'IN_TRANSIT_TO_DEST'
    COMPLETED = 'COMPLETED'
    CANCELLED = 'CANCELLED'
    TIMEOUT_NO_DRIVERS = 'TIMEOUT_NO_DRIVERS'

class TowRequest(db.Model):
    __tablename__ = 'tow_requests'

    # Identificador único global (Idempotencia)
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    
    # Participantes
    client_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    client = db.relationship('User', back_populates='requests', foreign_keys=[client_id])
    
    # Grúa asignada (una vez aceptada la oferta)
    truck_id = db.Column(db.Integer, db.ForeignKey('tow_trucks.id'), nullable=True, index=True)
    assigned_truck = db.relationship('TowTruck', back_populates='assigned_requests', foreign_keys=[truck_id])

    # Gestión de despacho bidireccional (Oferta activa)
    offered_truck_id = db.Column(db.Integer, db.ForeignKey('tow_trucks.id'), nullable=True, index=True)
    offered_truck = db.relationship('TowTruck', foreign_keys=[offered_truck_id])
    offered_at = db.Column(db.DateTime, nullable=True)
    offer_timeout_seconds = db.Column(db.Integer, default=30, nullable=False)
    rejected_truck_ids = db.Column(db.JSON, default=list, nullable=False)

    # Estado del ciclo de vida y pagos
    status = db.Column(db.Enum(TowRequestStatus), default=TowRequestStatus.PENDING, nullable=False, index=True)
    payment_status = db.Column(db.String(30), default='UNPAID', nullable=False, index=True) # UNPAID, HELD_IN_ESCROW, PAID, REFUNDED
    payments = db.relationship('Payment', back_populates='request', cascade='all, delete-orphan', lazy=True)

    # Coordenadas de origen (Lugar del siniestro o avería)
    origin_lat = db.Column(db.Float, nullable=False)
    origin_lng = db.Column(db.Float, nullable=False)
    origin_address = db.Column(db.String(255), nullable=True)

    # Coordenadas de destino (Taller o residencia, opcional)
    dest_lat = db.Column(db.Float, nullable=True)
    dest_lng = db.Column(db.Float, nullable=True)
    dest_address = db.Column(db.String(255), nullable=True)

    # Métricas de distancia
    distance_to_user_km = db.Column(db.Float, nullable=False)
    trip_distance_km = db.Column(db.Float, default=0.0, nullable=False)
    total_distance_km = db.Column(db.Float, nullable=False)

    # Finanzas en centavos enteros para evitar imprecisión de floats
    cost_ves_cents = db.Column(db.BigInteger, nullable=False)
    cost_usd_cents = db.Column(db.BigInteger, nullable=False)
    exchange_rate = db.Column(db.Numeric(12, 4), nullable=False)

    # Marcas temporales
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)
    completed_at = db.Column(db.DateTime, nullable=True)

    def to_dict(self):
        from app.services.geo_service import GeoService

        active_truck = self.assigned_truck or self.offered_truck
        truck_pos = None
        current_dist_km = round(self.distance_to_user_km, 2)

        if active_truck and active_truck.current_lat is not None and active_truck.current_lng is not None:
            truck_pos = {
                'lat': active_truck.current_lat,
                'lng': active_truck.current_lng
            }
            target_coords = (
                (self.dest_lat, self.dest_lng)
                if self.status == TowRequestStatus.IN_TRANSIT_TO_DEST and self.dest_lat is not None
                else (self.origin_lat, self.origin_lng)
            )
            current_dist_km = round(
                GeoService.calculate_distance_km((active_truck.current_lat, active_truck.current_lng), target_coords),
                2
            )

        eta_info = GeoService.calculate_eta(current_dist_km)

        return {
            'id': self.id,
            'client_id': self.client_id,
            'client_name': self.client.full_name if self.client else None,
            'client_phone': self.client.phone_number if self.client else None,
            'truck_id': self.truck_id,
            'truck_plate': self.assigned_truck.license_plate if self.assigned_truck else (self.offered_truck.license_plate if self.offered_truck else None),
            'truck_position': truck_pos,
            'driver_name': self.assigned_truck.driver.full_name if (self.assigned_truck and self.assigned_truck.driver) else None,
            'driver_phone': self.assigned_truck.driver.phone_number if (self.assigned_truck and self.assigned_truck.driver) else None,
            'offered_truck_id': self.offered_truck_id,
            'offered_at': self.offered_at.isoformat() if self.offered_at else None,
            'offer_timeout_seconds': self.offer_timeout_seconds,
            'status': self.status.value if isinstance(self.status, TowRequestStatus) else self.status,
            'payment_status': self.payment_status,
            'has_escrow': self.payment_status == 'HELD_IN_ESCROW',
            'origin': {
                'lat': self.origin_lat,
                'lng': self.origin_lng,
                'address': self.origin_address
            },
            'destination': {
                'lat': self.dest_lat,
                'lng': self.dest_lng,
                'address': self.dest_address
            } if self.dest_lat is not None else None,
            'metrics': {
                'distance_to_user_km': round(self.distance_to_user_km, 2),
                'distance_remaining_km': current_dist_km,
                'trip_distance_km': round(self.trip_distance_km, 2),
                'total_distance_km': round(self.total_distance_km, 2)
            },
            'eta': eta_info,
            'pricing': {
                'cost_ves': round(self.cost_ves_cents / 100.0, 2),
                'cost_usd': round(self.cost_usd_cents / 100.0, 2),
                'cost_ves_cents': self.cost_ves_cents,
                'cost_usd_cents': self.cost_usd_cents,
                'exchange_rate': float(self.exchange_rate)
            },
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat(),
            'completed_at': self.completed_at.isoformat() if self.completed_at else None
        }
