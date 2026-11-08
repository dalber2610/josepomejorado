from datetime import datetime, timezone
from app.extensions import db

class ExchangeRateLog(db.Model):
    __tablename__ = 'exchange_rate_logs'

    id = db.Column(db.Integer, primary_key=True)
    rate = db.Column(db.Numeric(12, 4), nullable=False)
    source = db.Column(db.String(50), default='BCV', nullable=False)
    fetched_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    def to_dict(self):
        return {
            'id': self.id,
            'rate': float(self.rate),
            'source': self.source,
            'fetched_at': self.fetched_at.isoformat()
        }
