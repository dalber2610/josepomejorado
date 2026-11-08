import unittest
import os
import sys
from decimal import Decimal

# Asegurar que el directorio raíz del proyecto esté en el path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app
from app.extensions import db
from app.models import User, UserRole, TowTruck, TowRequest, TowRequestStatus, Payment, PaymentStatus, PaymentMethod, OtpVerification
from app.services.otp_service import OtpService
from app.services.payment_service import PaymentService
from app.services.dispatch_service import DispatchService

class TestPhase3SecurityAndPayments(unittest.TestCase):
    def setUp(self):
        self.app = create_app('testing')
        self.app_context = self.app.app_context()
        self.app_context.push()
        db.create_all()

        # Crear usuarios de prueba
        self.client_user = User(
            email='client_test@josepo.com',
            phone_number='+584141112233',
            full_name='Cliente Test',
            role=UserRole.CLIENT
        )
        self.client_user.set_password('TestPass123!')
        db.session.add(self.client_user)

        self.driver_user = User(
            email='driver_test@josepo.com',
            phone_number='+584124445566',
            full_name='Chofer Test',
            role=UserRole.DRIVER
        )
        self.driver_user.set_password('TestPass123!')
        db.session.add(self.driver_user)
        db.session.commit()

        # Crear grúa
        self.truck = TowTruck(
            license_plate='TEST-001',
            brand_model='Ford Plataforma',
            driver_id=self.driver_user.id,
            current_lat=10.5000,
            current_lng=-66.9167,
            is_available=True,
            is_active=True
        )
        db.session.add(self.truck)
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    def test_otp_generation_and_verification(self):
        phone = "+584141112233"
        # 1. Solicitar OTP
        res = OtpService.request_otp(phone, purpose='SOS_LOGIN')
        self.assertEqual(res['status'], 'sent')
        self.assertEqual(res['phone_number'], phone)

        otp_record = OtpVerification.query.filter_by(phone_number=phone).first()
        self.assertIsNotNone(otp_record)
        self.assertFalse(otp_record.is_verified)

        # 2. Código erróneo falla
        with self.assertRaises(ValueError):
            OtpService.verify_otp_and_login(phone, "000000", purpose='SOS_LOGIN')

        # 3. Código correcto valida
        demo_code = res['demo_otp_code']
        verify_res = OtpService.verify_otp_and_login(phone, demo_code, purpose='SOS_LOGIN')
        self.assertEqual(verify_res['status'], 'verified')
        self.assertIn('access_token', verify_res)
        self.assertEqual(verify_res['user']['phone_number'], phone)

    def test_pago_movil_escrow_lifecycle(self):
        # 1. Crear solicitud de remolque
        req = TowRequest(
            client_id=self.client_user.id,
            truck_id=self.truck.id,
            status=TowRequestStatus.ASSIGNED,
            origin_lat=10.4900,
            origin_lng=-66.9000,
            distance_to_user_km=2.5,
            trip_distance_km=5.0,
            total_distance_km=7.5,
            cost_ves_cents=100000, # 1000.00 VES
            cost_usd_cents=2500,   # 25.00 USD
            exchange_rate=Decimal('40.0000')
        )
        db.session.add(req)
        db.session.commit()

        # 2. Registrar Pago Móvil en Escrow
        payment = PaymentService.register_pago_movil_escrow(
            client_id=self.client_user.id,
            request_id=req.id,
            bank_code='0134', # Banesco
            payer_phone='04141112233',
            payer_id_card='V-28123456',
            reference_number='987654'
        )

        self.assertEqual(payment.status, PaymentStatus.HELD_IN_ESCROW)
        self.assertEqual(req.payment_status, 'HELD_IN_ESCROW')
        # Verificar división de ingresos (85% Chofer = 85000 centavos, 15% Plataforma = 15000 centavos)
        self.assertEqual(payment.driver_payout_cents, 85000)
        self.assertEqual(payment.platform_fee_cents, 15000)
        self.assertEqual(payment.amount_ves_cents, 100000)

        # 3. Prevención de doble gasto (reutilizar referencia falla)
        with self.assertRaises(ValueError):
            PaymentService.register_pago_movil_escrow(
                client_id=self.client_user.id,
                request_id=req.id,
                bank_code='0134',
                payer_phone='04141112233',
                payer_id_card='V-28123456',
                reference_number='987654'
            )

        # 4. Liberar garantía al chofer al finalizar viaje
        released_payment = PaymentService.release_escrow_to_driver(req.id)
        self.assertEqual(released_payment.status, PaymentStatus.RELEASED_TO_DRIVER)
        self.assertEqual(req.payment_status, 'PAID')
        self.assertIsNotNone(released_payment.released_at)

    def test_pago_movil_escrow_refund(self):
        # 1. Crear solicitud y pago en garantía
        req = TowRequest(
            client_id=self.client_user.id,
            status=TowRequestStatus.ASSIGNED,
            origin_lat=10.4900,
            origin_lng=-66.9000,
            distance_to_user_km=2.0,
            total_distance_km=2.0,
            cost_ves_cents=50000,
            cost_usd_cents=1250,
            exchange_rate=Decimal('40.0000')
        )
        db.session.add(req)
        db.session.commit()

        payment = PaymentService.register_pago_movil_escrow(
            client_id=self.client_user.id,
            request_id=req.id,
            bank_code='0102',
            payer_phone='04141112233',
            payer_id_card='V-28123456',
            reference_number='112233'
        )

        # 2. Reembolsar por cancelación
        refunded = PaymentService.refund_escrow(req.id, reason="Cancelación de emergencia")
        self.assertEqual(refunded.status, PaymentStatus.REFUNDED)
        self.assertEqual(req.payment_status, 'REFUNDED')
        self.assertIsNotNone(refunded.refunded_at)

if __name__ == '__main__':
    unittest.main()
