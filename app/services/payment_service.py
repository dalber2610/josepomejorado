from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
import uuid
import logging
from sqlalchemy.exc import IntegrityError
from app.extensions import db, socketio
from app.models.payment import Payment, PaymentStatus, PaymentMethod
from app.models.tow_request import TowRequest, TowRequestStatus
from app.services.currency_service import CurrencyService

logger = logging.getLogger(__name__)


class PaymentService:
    """Motor de gestión de pagos, escrow de garantía y Pago Móvil interbancario."""

    VENEZUELAN_BANKS = [
        {'code': '0102', 'name': 'Banco de Venezuela'},
        {'code': '0104', 'name': 'Venezolano de Crédito'},
        {'code': '0105', 'name': 'Banco Mercantil'},
        {'code': '0108', 'name': 'BBVA Banco Provincial'},
        {'code': '0114', 'name': 'Bancaribe'},
        {'code': '0115', 'name': 'Banco Exterior'},
        {'code': '0128', 'name': 'Banco Caroní'},
        {'code': '0134', 'name': 'Banesco Banco Universal'},
        {'code': '0137', 'name': 'Banco Sofitasa'},
        {'code': '0138', 'name': 'Banco Plaza'},
        {'code': '0151', 'name': 'BFC Banco Fondo Común'},
        {'code': '0156', 'name': '100% Banco'},
        {'code': '0157', 'name': 'DelSur Banco Universal'},
        {'code': '0163', 'name': 'Banco del Tesoro'},
        {'code': '0168', 'name': 'Bancrecer'},
        {'code': '0169', 'name': 'Mi Banco'},
        {'code': '0171', 'name': 'Banco Activo'},
        {'code': '0172', 'name': 'Bancamiga Banco Universal'},
        {'code': '0174', 'name': 'Banplus Banco Universal'},
        {'code': '0175', 'name': 'Banco Bicentenario'},
        {'code': '0177', 'name': 'BANFANB'},
        {'code': '0191', 'name': 'Banco Nacional de Crédito (BNC)'}
    ]

    @classmethod
    def get_supported_banks(cls) -> list:
        """Retorna el directorio oficial de códigos bancarios de Venezuela."""
        return cls.VENEZUELAN_BANKS

    @classmethod
    def register_pago_movil_escrow(cls, client_id: int, request_id: str,
                                   bank_code: str, payer_phone: str,
                                   payer_id_card: str, reference_number: str) -> Payment:
        """
        Registra un Pago Móvil y lo retiene en Depósito de Garantía (Escrow).
        Mitigación Hallazgo C:
        1. Bloqueo pesimista transaccional (`with_for_update()`) para evitar condiciones de carrera y pagos dobles.
        2. Recálculo autoritativo en el servidor consultando `CurrencyService` y `ExchangeRateLog` con `Decimal` y centavos (`int`).
        """
        try:
            # Bloqueo de fila atómico sobre la solicitud para evitar condiciones de carrera (Race Conditions)
            tow_req = TowRequest.query.filter_by(id=request_id).with_for_update().first()
            if not tow_req:
                raise ValueError("Solicitud de remolque no encontrada.")

            if tow_req.client_id != client_id:
                raise PermissionError("No tienes permisos para registrar pagos en esta solicitud.")

            if tow_req.status in [TowRequestStatus.CANCELLED, TowRequestStatus.TIMEOUT_NO_DRIVERS]:
                raise ValueError("No se puede registrar un pago para una solicitud cancelada o expirada.")

            # Verificar que la solicitud no tenga ya un pago activo o liberado (Evitar Doble Cobro)
            existing_req_payment = Payment.query.filter(
                Payment.request_id == tow_req.id,
                Payment.status.in_([PaymentStatus.HELD_IN_ESCROW, PaymentStatus.RELEASED_TO_DRIVER])
            ).with_for_update().first()
            if existing_req_payment:
                raise ValueError("Esta solicitud ya cuenta con una garantía de pago activa o liquidada.")

            # Limpiar y sanitizar datos bancarios
            clean_ref = str(reference_number).strip().replace(" ", "")
            if not clean_ref or len(clean_ref) < 4 or not clean_ref.isdigit():
                raise ValueError("El número de referencia debe contener al menos 4 dígitos numéricos.")

            # Prevención estricta de doble gasto por número de referencia (Double Spending)
            existing_ref = Payment.query.filter_by(reference_number=clean_ref).with_for_update().first()
            if existing_ref:
                raise ValueError(f"La referencia bancaria #{clean_ref} ya fue registrada en otra transacción.")

            clean_bank_code = str(bank_code).strip()
            bank_obj = next((b for b in cls.VENEZUELAN_BANKS if b['code'] == clean_bank_code), None)
            if not bank_obj:
                raise ValueError("Código de banco emisor no válido en el directorio nacional.")
            bank_name = bank_obj['name']

            # Cálculo autoritativo de montos y tasa oficial en el servidor (Anti-Parameter Tampering):
            # Jamás se reciben montos desde el navegador; se toman de la orden creada en servidor
            # o se recalculan con CurrencyService si la orden aún no tenía tarifa fijada.
            if not tow_req.cost_ves_cents or tow_req.cost_ves_cents <= 0 or not tow_req.cost_usd_cents:
                authoritative_pricing = CurrencyService.calculate_cost(tow_req.total_distance_km)
                official_rate = Decimal(str(authoritative_pricing['exchange_rate'])).quantize(
                    Decimal('0.0001'), rounding=ROUND_HALF_UP
                )
                total_ves_cents = int(authoritative_pricing['cost_ves_cents'])
                total_usd_cents = int(authoritative_pricing['cost_usd_cents'])
                tow_req.cost_ves_cents = total_ves_cents
                tow_req.cost_usd_cents = total_usd_cents
                tow_req.exchange_rate = official_rate
            else:
                total_ves_cents = int(tow_req.cost_ves_cents)
                total_usd_cents = int(tow_req.cost_usd_cents)
                official_rate = Decimal(str(tow_req.exchange_rate)).quantize(
                    Decimal('0.0001'), rounding=ROUND_HALF_UP
                )

            # Calcular split en centavos exactos (85% para el chofer, 15% para la plataforma)
            driver_payout_cents, platform_fee_cents = Payment.calculate_split(total_ves_cents, Decimal('0.85'))

            # Identificar chofer si ya está asignado
            driver_user_id = None
            if tow_req.assigned_truck and tow_req.assigned_truck.driver_id:
                driver_user_id = tow_req.assigned_truck.driver_id

            # Crear registro de pago retenido en Escrow
            payment = Payment(
                id=str(uuid.uuid4()),
                request_id=tow_req.id,
                client_id=client_id,
                driver_id=driver_user_id,
                amount_ves_cents=total_ves_cents,
                amount_usd_cents=total_usd_cents,
                exchange_rate=official_rate,
                driver_payout_cents=driver_payout_cents,
                platform_fee_cents=platform_fee_cents,
                method=PaymentMethod.PAGO_MOVIL,
                status=PaymentStatus.HELD_IN_ESCROW,
                reference_number=clean_ref,
                bank_code=clean_bank_code,
                bank_name=bank_name,
                payer_phone=payer_phone.strip(),
                payer_id_card=payer_id_card.strip().upper(),
                held_at=datetime.now(timezone.utc)
            )

            tow_req.payment_status = 'HELD_IN_ESCROW'
            db.session.add(payment)
            db.session.commit()

        except IntegrityError:
            db.session.rollback()
            raise ValueError("Transacción duplicada detectada de forma concurrente. La referencia ya está en uso.")
        except Exception:
            db.session.rollback()
            raise

        # Notificar en tiempo real a cliente y chofer
        cls._notify_escrow_event(payment, 'payment_held', 'Garantía de Pago Móvil congelada en Escrow.')

        return payment

    @classmethod
    def release_escrow_to_driver(cls, request_id: str) -> Payment:
        """
        Libera los fondos congelados y acredita las ganancias al conductor
        una vez que el remolque alcanza el destino final con estatus COMPLETED.
        Usa bloqueo de fila `with_for_update()` para evitar liberaciones duplicadas.
        """
        payment = Payment.query.filter_by(request_id=request_id).order_by(
            Payment.created_at.desc()
        ).with_for_update().first()
        if not payment:
            return None

        tow_req = TowRequest.query.filter_by(id=request_id).with_for_update().first()

        if payment.status == PaymentStatus.HELD_IN_ESCROW:
            payment.status = PaymentStatus.RELEASED_TO_DRIVER
            payment.released_at = datetime.now(timezone.utc)
            if tow_req:
                tow_req.payment_status = 'PAID'
            db.session.commit()

            cls._notify_escrow_event(
                payment,
                'payment_released',
                f"¡Pago Liberado! Se han acreditado {round(payment.driver_payout_cents / 100.0, 2)} VES a la cuenta del conductor."
            )

        return payment

    @classmethod
    def refund_escrow(cls, request_id: str, reason: str = 'Servicio cancelado') -> Payment:
        """
        Reembolsa la garantía retenida en caso de cancelación del viaje
        o indisponibilidad de unidades de grúa con bloqueo transaccional.
        """
        payment = Payment.query.filter_by(request_id=request_id).order_by(
            Payment.created_at.desc()
        ).with_for_update().first()
        if not payment:
            return None

        tow_req = TowRequest.query.filter_by(id=request_id).with_for_update().first()

        if payment.status in [PaymentStatus.HELD_IN_ESCROW, PaymentStatus.PENDING]:
            payment.status = PaymentStatus.REFUNDED
            payment.refunded_at = datetime.now(timezone.utc)
            if tow_req:
                tow_req.payment_status = 'REFUNDED'
            db.session.commit()

            cls._notify_escrow_event(
                payment,
                'payment_refunded',
                f"Garantía de pago reembolsada. Motivo: {reason}."
            )

        return payment

    @classmethod
    def _notify_escrow_event(cls, payment: Payment, event_name: str, message: str):
        """Emite eventos a las salas privadas WebSocket de cliente y conductor."""
        payload = payment.to_dict()
        payload['notification_message'] = message

        socketio.emit(event_name, payload, room=f"user_{payment.client_id}")
        if payment.driver_id:
            socketio.emit(event_name, payload, room=f"driver_{payment.driver_id}")
