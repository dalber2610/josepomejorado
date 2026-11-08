from datetime import datetime, timezone
from sqlalchemy import func
from app.extensions import db
from app.models.tow_truck import TowTruck
from app.models.tow_request import TowRequest, TowRequestStatus
from app.models.payment import Payment, PaymentStatus
from app.models.service_contract import ServiceContract
from app.models.traffic_report import TrafficReport
from app.models.user import User, UserRole
from app.services.currency_service import CurrencyService

class AdminService:
    """Motor de Business Intelligence, analítica de SLA y Centro de Control de Operaciones."""

    @classmethod
    def get_dashboard_kpis(cls) -> dict:
        """Calcula los indicadores clave de rendimiento (KPIs) en tiempo real."""
        # 1. Métricas de Flota
        total_trucks = TowTruck.query.count()
        active_trucks = TowTruck.query.filter_by(is_active=True).count()
        available_trucks = TowTruck.query.filter_by(is_active=True, is_available=True).count()
        busy_trucks = TowTruck.query.filter_by(is_active=True, is_available=False).count()

        # 2. Métricas de Solicitudes y Servicios
        total_requests = TowRequest.query.count()
        completed_requests = TowRequest.query.filter_by(status=TowRequestStatus.COMPLETED).count()
        cancelled_requests = TowRequest.query.filter_by(status=TowRequestStatus.CANCELLED).count()
        in_progress_requests = TowRequest.query.filter(
            TowRequest.status.in_([
                TowRequestStatus.ASSIGNED,
                TowRequestStatus.IN_TRANSIT_TO_USER,
                TowRequestStatus.ARRIVED_AT_USER,
                TowRequestStatus.IN_TRANSIT_TO_DEST
            ])
        ).count()

        # 3. Auditoría de SLA y Tiempos de Respuesta
        total_contracts = ServiceContract.query.count()
        sla_met_count = ServiceContract.query.filter_by(sla_met=True).count()
        sla_compliance_rate = round((sla_met_count / total_contracts * 100.0), 1) if total_contracts > 0 else 100.0

        avg_arrival_minutes = db.session.query(func.avg(ServiceContract.sla_actual_minutes)).scalar()
        avg_arrival_minutes = round(float(avg_arrival_minutes), 1) if avg_arrival_minutes is not None else 18.5

        avg_rating = db.session.query(func.avg(ServiceContract.client_rating)).filter(ServiceContract.client_rating.isnot(None)).scalar()
        avg_rating = round(float(avg_rating), 1) if avg_rating is not None else 5.0

        # 4. Métricas Financieras y Split 85/15
        total_gross_cents = db.session.query(func.sum(Payment.amount_usd_cents)).filter(
            Payment.status.in_([PaymentStatus.CONFIRMED, PaymentStatus.RELEASED_TO_DRIVER, PaymentStatus.HELD_IN_ESCROW])
        ).scalar() or 0

        driver_payout_usd_cents = db.session.query(func.sum(Payment.driver_payout_cents)).filter(
            Payment.status == PaymentStatus.RELEASED_TO_DRIVER
        ).scalar() or 0

        platform_revenue_usd_cents = db.session.query(func.sum(Payment.platform_fee_cents)).filter(
            Payment.status == PaymentStatus.RELEASED_TO_DRIVER
        ).scalar() or 0

        escrow_held_usd_cents = db.session.query(func.sum(Payment.amount_usd_cents)).filter(
            Payment.status == PaymentStatus.HELD_IN_ESCROW
        ).scalar() or 0

        current_rate = CurrencyService.get_current_bcv_rate()

        return {
            'fleet': {
                'total_units': total_trucks,
                'active_on_shift': active_trucks,
                'available': available_trucks,
                'busy_in_service': busy_trucks
            },
            'operations': {
                'total_requests': total_requests,
                'completed': completed_requests,
                'cancelled': cancelled_requests,
                'in_progress': in_progress_requests,
                'traffic_reports_count': TrafficReport.query.count()
            },
            'sla': {
                'compliance_percentage': sla_compliance_rate,
                'average_arrival_minutes': avg_arrival_minutes,
                'target_minutes': 30,
                'average_customer_rating': avg_rating
            },
            'financials': {
                'gross_volume_usd': round(total_gross_cents / 100.0, 2),
                'gross_volume_ves': round((total_gross_cents / 100.0) * float(current_rate), 2),
                'driver_payouts_usd': round(driver_payout_usd_cents / 100.0, 2),
                'platform_commission_usd': round(platform_revenue_usd_cents / 100.0, 2),
                'escrow_held_usd': round(escrow_held_usd_cents / 100.0, 2),
                'bcv_rate': float(current_rate)
            }
        }

    @classmethod
    def get_fleet_telemetry_live(cls) -> list:
        """Retorna el listado completo de unidades de grúa con telemetría en tiempo real."""
        trucks = TowTruck.query.all()
        return [t.to_dict() for t in trucks]

    @classmethod
    def get_recent_operations(cls, limit: int = 15) -> list:
        """Retorna las operaciones más recientes para la consola del operador."""
        reqs = TowRequest.query.order_by(TowRequest.created_at.desc()).limit(limit).all()
        return [r.to_dict() for r in reqs]

