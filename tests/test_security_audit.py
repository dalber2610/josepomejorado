import unittest
import os
import sys
import hmac
import hashlib
import json
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from sqlalchemy import text

# Asegurar que el directorio raíz del proyecto esté en el path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app
from app.config import ProductionConfig
from app.extensions import db, limiter
from app.models import (
    User, UserRole, TowTruck, TowRequest, TowRequestStatus,
    Payment, PaymentStatus, OtpVerification
)
from app.services.otp_service import OtpService
from app.services.geo_service import GeoService
from app.utils.rate_limiter import otp_rate_limiter, auth_rate_limiter
from scripts.package_release import should_exclude


class TestProductionSecurityAudit(unittest.TestCase):
    """
    Suite de Pruebas de Auditoría de Seguridad y Arquitectura (Hallazgos A, B, C, D y E).
    """

    def setUp(self):
        self.app = create_app('testing')
        self.client = self.app.test_client()
        self.app_context = self.app.app_context()
        self.app_context.push()
        db.create_all()
        otp_rate_limiter.reset()
        auth_rate_limiter.reset()
        limiter.reset()

        # Crear usuarios de prueba
        self.client_user = User(
            email='audit_client@josepo.com',
            phone_number='+584140001122',
            full_name='Cliente Auditoría',
            role=UserRole.CLIENT
        )
        self.client_user.set_password('ClientPass2026!')
        db.session.add(self.client_user)

        self.driver_user = User(
            email='audit_driver@josepo.com',
            phone_number='+584120003344',
            full_name='Chofer Auditoría',
            role=UserRole.DRIVER
        )
        self.driver_user.set_password('DriverPass2026!')
        db.session.add(self.driver_user)
        db.session.commit()

        # Crear grúa vinculada al chofer
        self.truck = TowTruck(
            license_plate='AUD-001',
            brand_model='Ford F-350 Plataforma',
            driver_id=self.driver_user.id,
            current_lat=10.5000,
            current_lng=-66.9167,
            is_available=True,
            is_active=True
        )
        db.session.add(self.truck)
        db.session.commit()

    def tearDown(self):
        otp_rate_limiter.reset()
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    def _get_jwt(self, email: str, password: str) -> str:
        res = self.client.post('/api/auth/login', json={'email': email, 'password': password})
        data = res.get_json()
        return data['access_token']

    # =========================================================================
    # HALLAZGO A: Fuga de Artefactos en Empaquetado
    # =========================================================================
    def test_finding_a_packaging_excludes_sensitive_artifacts(self):
        """Verifica que el empaquetador excluya bases de datos locales, venv/, __pycache__ y .env."""
        self.assertTrue(should_exclude('instance/josepo_dev.db'))
        self.assertTrue(should_exclude('venv/Scripts/python.exe'))
        self.assertTrue(should_exclude('venv/.env.example'))
        self.assertTrue(should_exclude('app/__pycache__/config.cpython-312.pyc'))
        self.assertTrue(should_exclude('.env'))
        # Archivos legítimos sí deben incluirse
        self.assertFalse(should_exclude('app/services/payment_service.py'))
        self.assertFalse(should_exclude('.env.example'))
        self.assertFalse(should_exclude('Dockerfile'))

    # =========================================================================
    # HALLAZGO B: Concurrencia de Base de Datos y Bloqueo de SQLite en Producción
    # =========================================================================
    def test_finding_b_production_config_blocks_sqlite(self):
        """Verifica que ProductionConfig rechace iniciar con SQLite en producción."""
        original_uri = ProductionConfig.SQLALCHEMY_DATABASE_URI
        original_secret = ProductionConfig.SECRET_KEY
        original_jwt = ProductionConfig.JWT_SECRET_KEY
        try:
            ProductionConfig.SECRET_KEY = 'a' * 64
            ProductionConfig.JWT_SECRET_KEY = 'b' * 64
            ProductionConfig.SQLALCHEMY_DATABASE_URI = 'sqlite:///josepo_prod.db'
            with self.assertRaises(ValueError) as ctx:
                ProductionConfig.validate()
            self.assertIn('SQLite', str(ctx.exception))
        finally:
            ProductionConfig.SQLALCHEMY_DATABASE_URI = original_uri
            ProductionConfig.SECRET_KEY = original_secret
            ProductionConfig.JWT_SECRET_KEY = original_jwt

    def test_finding_b_sqlite_busy_timeout_and_foreign_keys(self):
        """Verifica que el motor SQLite configure busy_timeout >= 10000ms y foreign_keys=ON."""
        timeout_row = db.session.execute(text("PRAGMA busy_timeout;")).fetchone()
        fk_row = db.session.execute(text("PRAGMA foreign_keys;")).fetchone()
        self.assertGreaterEqual(int(timeout_row[0]), 10000)
        self.assertEqual(int(fk_row[0]), 1)

    # =========================================================================
    # HALLAZGO C: Vulnerabilidades en Pagos, Parameter Tampering y Webhook HMAC
    # =========================================================================
    def test_finding_c_reject_parameter_tampering_in_payments(self):
        """Verifica que enviar montos o tasas adulteradas desde el cliente sea rechazado con HTTP 400."""
        token = self._get_jwt('audit_client@josepo.com', 'ClientPass2026!')

        req = TowRequest(
            client_id=self.client_user.id,
            truck_id=self.truck.id,
            status=TowRequestStatus.ASSIGNED,
            origin_lat=10.4900,
            origin_lng=-66.9000,
            distance_to_user_km=3.0,
            total_distance_km=5.0,
            cost_ves_cents=120000,
            cost_usd_cents=3000,
            exchange_rate=Decimal('40.0000')
        )
        db.session.add(req)
        db.session.commit()

        # Intento de ataque Parameter Tampering: enviar amount_ves_cents=100 (1.00 VES) y exchange_rate=1.0
        tampered_payload = {
            'request_id': req.id,
            'bank_code': '0134',
            'payer_phone': '04140001122',
            'payer_id_card': 'V-20111222',
            'reference_number': '556677',
            'amount_ves_cents': 100,
            'exchange_rate': '1.00'
        }
        res = self.client.post(
            '/api/payments/pago-movil/escrow',
            headers={'Authorization': f'Bearer {token}'},
            json=tampered_payload
        )
        self.assertEqual(res.status_code, 400)
        self.assertIn('Manipulación', res.get_json().get('error', ''))

    def test_finding_c_webhook_requires_valid_hmac_signature(self):
        """Verifica que el webhook bancario rechace peticiones sin firma HMAC-SHA256 válida."""
        req = TowRequest(
            client_id=self.client_user.id,
            truck_id=self.truck.id,
            status=TowRequestStatus.ASSIGNED,
            origin_lat=10.4900,
            origin_lng=-66.9000,
            distance_to_user_km=3.0,
            total_distance_km=5.0,
            cost_ves_cents=100000,
            cost_usd_cents=2500,
            exchange_rate=Decimal('40.0000')
        )
        db.session.add(req)
        db.session.commit()

        payment = Payment(
            request_id=req.id,
            client_id=self.client_user.id,
            status=PaymentStatus.PENDING,
            amount_ves_cents=100000,
            amount_usd_cents=2500,
            exchange_rate=Decimal('40.0000'),
            platform_fee_cents=15000,
            driver_payout_cents=85000,
            bank_code='0134',
            payer_phone='04140001122',
            payer_id_card='V-20111222',
            reference_number='998877'
        )
        db.session.add(payment)
        db.session.commit()

        body_bytes = json.dumps({
            'reference_number': '998877',
            'bank_code': '0134',
            'amount_ves_cents': 100000,
            'status': 'APPROVED'
        }).encode('utf-8')

        # 1. Sin firma HMAC -> 401 Unauthorized
        res_no_sig = self.client.post(
            '/api/payments/webhook',
            data=body_bytes,
            content_type='application/json'
        )
        self.assertEqual(res_no_sig.status_code, 401)

        # 2. Con firma HMAC válida pero monto discrepante -> 400 Bad Request
        secret = self.app.config['WEBHOOK_SECRET']
        bad_amount_bytes = json.dumps({
            'reference_number': '998877',
            'bank_code': '0134',
            'amount_ves_cents': 500,  # Monto inferior al esperado
            'status': 'APPROVED'
        }).encode('utf-8')
        bad_sig = hmac.new(secret.encode('utf-8'), bad_amount_bytes, hashlib.sha256).hexdigest()
        res_bad_amount = self.client.post(
            '/api/payments/webhook',
            data=bad_amount_bytes,
            headers={'X-Webhook-Signature': bad_sig},
            content_type='application/json'
        )
        self.assertEqual(res_bad_amount.status_code, 400)

        # 3. Con firma HMAC válida y monto exacto -> 200 OK
        valid_sig = hmac.new(secret.encode('utf-8'), body_bytes, hashlib.sha256).hexdigest()
        res_valid = self.client.post(
            '/api/payments/webhook',
            data=body_bytes,
            headers={'X-Webhook-Signature': valid_sig},
            content_type='application/json'
        )
        self.assertEqual(res_valid.status_code, 200)

    # =========================================================================
    # HALLAZGO D: Protección Anti-Fuerza Bruta y Rate Limiting en OTP
    # =========================================================================
    def test_finding_d_otp_invalidates_immediately_on_third_failed_attempt(self):
        """Verifica que al 3er intento fallido el código OTP quede revocado incluso si luego se envía el código real."""
        phone = "+584147778899"
        res = OtpService.request_otp(phone, purpose='SOS_LOGIN')
        real_code = res['demo_otp_code']

        # Intentos 1, 2 y 3 con código falso
        for _ in range(3):
            with self.assertRaises(ValueError):
                OtpService.verify_otp_and_login(phone, "000000", purpose='SOS_LOGIN')

        # 4to intento usando el código real: debe fallar porque el OTP ya fue revocado en el 3er fallo
        with self.assertRaises(ValueError) as ctx:
            OtpService.verify_otp_and_login(phone, real_code, purpose='SOS_LOGIN')
        self.assertIn("invalidado", str(ctx.exception).lower())

    def test_finding_d_otp_endpoint_rate_limiter_blocks_flood(self):
        """Verifica que el Rate Limiter bloquee ráfagas de solicitudes OTP con HTTP 429."""
        for i in range(5):
            r = self.client.post('/api/auth/otp/send', json={'phone_number': f'+58414111220{i}'})
            self.assertEqual(r.status_code, 200)

        # La 6ta petición desde la misma IP dentro de la ventana debe retornar 429 Too Many Requests
        r_blocked = self.client.post('/api/auth/otp/send', json={'phone_number': '+584141112299'})
        self.assertEqual(r_blocked.status_code, 429)
        self.assertIn('retry_after_seconds', r_blocked.get_json())

    # =========================================================================
    # HALLAZGO E: Prevención de GPS Spoofing y Suplantación de Unidades
    # =========================================================================
    def test_finding_e_kinematic_validation_blocks_impossible_gps_jump(self):
        """Verifica que un salto de ~11 km en 2 segundos (> 20,000 km/h) sea bloqueado como GPS Spoofing."""
        now = datetime.now(timezone.utc)
        two_seconds_ago = now - timedelta(seconds=2)

        # Salto desde Caracas (10.5000, -66.9167) hasta La Guaira (10.6000, -66.9333) en 2 segundos
        is_valid, speed_kmh, _ = GeoService.validate_kinematic_movement(
            prev_lat=10.5000,
            prev_lng=-66.9167,
            prev_timestamp=two_seconds_ago,
            new_lat=10.6000,
            new_lng=-66.9333,
            new_timestamp=now
        )
        self.assertFalse(is_valid)
        self.assertGreater(speed_kmh, 180.0)

        # Movimiento realista (~25 metros en 3 segundos)
        is_valid_real, _, _ = GeoService.validate_kinematic_movement(
            prev_lat=10.5000,
            prev_lng=-66.9167,
            prev_timestamp=now - timedelta(seconds=3),
            new_lat=10.5002,
            new_lng=-66.9167,
            new_timestamp=now
        )
        self.assertTrue(is_valid_real)

    def test_finding_e_telemetry_endpoint_blocks_mock_location_and_spoofing(self):
        """Verifica que /api/driver/telemetry rechace is_mocked=True, otra unidad y saltos irreales."""
        driver_token = self._get_jwt('audit_driver@josepo.com', 'DriverPass2026!')

        # 1. Rechazar Mock Location (Fake GPS app en Android/iOS)
        res_mock = self.client.post(
            '/api/driver/telemetry',
            headers={'Authorization': f'Bearer {driver_token}'},
            json={'lat': 10.5001, 'lng': -66.9167, 'is_mocked': True}
        )
        self.assertEqual(res_mock.status_code, 403)

        # 2. Rechazar intento de mover otra grúa (truck_id ajeno)
        res_other_truck = self.client.post(
            '/api/driver/telemetry',
            headers={'Authorization': f'Bearer {driver_token}'},
            json={'truck_id': 9999, 'lat': 10.5001, 'lng': -66.9167}
        )
        self.assertEqual(res_other_truck.status_code, 403)

        # 3. Rechazar teletransportación (salto de 50 km inmediato)
        self.truck.update_position(10.5000, -66.9167)
        db.session.commit()

        res_teleport = self.client.post(
            '/api/driver/telemetry',
            headers={'Authorization': f'Bearer {driver_token}'},
            json={'lat': 10.9500, 'lng': -66.9167}
        )
        self.assertEqual(res_teleport.status_code, 400)
        self.assertIn('Anti-Spoofing', res_teleport.get_json().get('error', ''))


if __name__ == '__main__':
    unittest.main()
