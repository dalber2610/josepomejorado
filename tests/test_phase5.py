import unittest
import os
import sys
from decimal import Decimal

# Asegurar que el directorio raíz del proyecto esté en el path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app
from app.config import BaseConfig, ProductionConfig
from app.extensions import db, limiter, DEFAULT_ALLOWED_ORIGINS
from app.models import (
    User, UserRole, ReputationLevel, TrafficReport,
    PartnerReward, RewardRedemption, PointTransaction, FamilySosAlert, ExchangeRateLog
)
from app.services.gamification_service import GamificationService
from app.services.currency_service import CurrencyService
from app.utils.rate_limiter import otp_rate_limiter, auth_rate_limiter
from app.utils.schema_validator import SchemaValidator


class TestPhase5AndClosureSuite(unittest.TestCase):
    """
    Suite de Pruebas Unitarias y de Integración de Cierre (Fases 5 y 7):
    1. Sistema de Puntos, Niveles de Reputación Vial y Canje en Talleres Aliados.
    2. Validación Cruzada de Tráfico (+25 pts al crear, +10 pts al confirmar, +15/+20 pts al autor).
    3. Botón SOS Familiar y Comandos de Voz con enlace de rastreo satelital en vivo.
    4. Blindaje de Producción (PostgreSQL+PostGIS, Flask-Limiter, CORS restrictivo, Validación de Esquemas y Cronjob Cambiario BCV).
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

        # Crear 3 usuarios para pruebas de validación cruzada comunitaria
        self.user_a = User(
            email='autor_vial@josepo.com',
            phone_number='+584141000001',
            full_name='Carlos Autor Vial',
            role=UserRole.CLIENT
        )
        self.user_a.set_password('Pass2026!')

        self.user_b = User(
            email='validador1@josepo.com',
            phone_number='+584141000002',
            full_name='Elena Validadora 1',
            role=UserRole.CLIENT
        )
        self.user_b.set_password('Pass2026!')

        self.user_c = User(
            email='validador2@josepo.com',
            phone_number='+584141000003',
            full_name='Pedro Validador 2',
            role=UserRole.DRIVER
        )
        self.user_c.set_password('Pass2026!')

        db.session.add_all([self.user_a, self.user_b, self.user_c])
        db.session.commit()

        GamificationService.ensure_default_catalog()

    def tearDown(self):
        CurrencyService.stop_exchange_rate_cron()
        otp_rate_limiter.reset()
        auth_rate_limiter.reset()
        limiter.reset()
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    def _login(self, email: str) -> str:
        res = self.client.post('/api/auth/login', json={'email': email, 'password': 'Pass2026!'})
        return res.get_json()['access_token']

    def test_01_points_reputation_and_reward_redemption(self):
        """Verifica acumulación de puntos, ascenso de nivel de reputación y canje de cupones en talleres."""
        token_a = self._login('autor_vial@josepo.com')

        # Nivel inicial: BRONCE (0 pts)
        self.assertEqual(self.user_a.points_balance, 0)
        self.assertEqual(self.user_a.reputation_level, ReputationLevel.BRONCE.value)

        # Otorgar 120 puntos -> debe ascender a PLATA (>= 100 pts)
        GamificationService.award_points(
            user_id=self.user_a.id,
            points=120,
            reason_code='TEST_BONUS',
            description='Bono de prueba vial'
        )
        db.session.refresh(self.user_a)
        self.assertEqual(self.user_a.points_balance, 120)
        self.assertEqual(self.user_a.lifetime_points, 120)
        self.assertEqual(self.user_a.reputation_level, ReputationLevel.PLATA.value)

        # Consultar catálogo de talleres aliados
        res_cat = self.client.get('/api/gamification/rewards')
        self.assertEqual(res_cat.status_code, 200)
        rewards = res_cat.get_json()['rewards']
        self.assertGreaterEqual(len(rewards), 5)

        # Canjear el primer beneficio (50 pts - Diagnóstico Computarizado OBD-II)
        first_reward = rewards[0]
        self.assertEqual(first_reward['points_cost'], 50)

        res_redeem = self.client.post(
            '/api/gamification/redeem',
            headers={'Authorization': f'Bearer {token_a}'},
            json={'reward_id': first_reward['id']}
        )
        self.assertEqual(res_redeem.status_code, 201)
        redeem_data = res_redeem.get_json()
        self.assertEqual(redeem_data['points_balance'], 70)  # 120 - 50 = 70 pts restantes
        self.assertTrue(redeem_data['redemption']['coupon_code'].startswith('JOSEPO-'))

        # Intentar canjear beneficio de 200 pts con solo 70 pts disponibles -> 400 Bad Request
        expensive_reward = rewards[-1]
        res_fail = self.client.post(
            '/api/gamification/redeem',
            headers={'Authorization': f'Bearer {token_a}'},
            json={'reward_id': expensive_reward['id']}
        )
        self.assertEqual(res_fail.status_code, 400)
        self.assertIn('Puntos insuficientes', res_fail.get_json()['error'])

    def test_02_traffic_report_cross_validation_and_points(self):
        """Verifica la suma automática de puntos al crear y confirmar reportes viales entre distintos usuarios."""
        token_a = self._login('autor_vial@josepo.com')
        token_b = self._login('validador1@josepo.com')
        token_c = self._login('validador2@josepo.com')

        # 1. Usuario A crea un reporte de accidente -> Gana +25 pts
        res_create = self.client.post(
            '/api/traffic/reports',
            headers={'Authorization': f'Bearer {token_a}'},
            json={
                'lat': 10.4950,
                'lng': -66.8900,
                'type': 'ACCIDENT',
                'description': 'Choque múltiple en autopista sentido centro'
            }
        )
        self.assertEqual(res_create.status_code, 201)
        report_id = res_create.get_json()['report']['id']
        db.session.refresh(self.user_a)
        self.assertEqual(self.user_a.points_balance, 25)

        # 2. Usuario A intenta auto-confirmar su propio reporte -> Rechazado (400)
        res_self = self.client.post(
            f'/api/traffic/reports/{report_id}/confirm',
            headers={'Authorization': f'Bearer {token_a}'}
        )
        self.assertEqual(res_self.status_code, 400)

        # 3. Usuario B confirma el reporte (1ra confirmación) -> B gana +10 pts, A gana +15 pts (Total A = 40)
        res_conf1 = self.client.post(
            f'/api/traffic/reports/{report_id}/confirm',
            headers={'Authorization': f'Bearer {token_b}'}
        )
        self.assertEqual(res_conf1.status_code, 200)
        db.session.refresh(self.user_a)
        db.session.refresh(self.user_b)
        self.assertEqual(self.user_b.points_balance, 10)
        self.assertEqual(self.user_a.points_balance, 40)

        # 4. Usuario B intenta confirmar por segunda vez el mismo reporte -> Rechazado (400)
        res_dup = self.client.post(
            f'/api/traffic/reports/{report_id}/confirm',
            headers={'Authorization': f'Bearer {token_b}'}
        )
        self.assertEqual(res_dup.status_code, 400)

        # 5. Usuario C confirma el reporte (2da confirmación -> Verificado!)
        # C gana +10 pts; A gana +15 pts + 20 pts de bono de verificación = +35 pts (Total A = 75)
        res_conf2 = self.client.post(
            f'/api/traffic/reports/{report_id}/confirm',
            headers={'Authorization': f'Bearer {token_c}'}
        )
        self.assertEqual(res_conf2.status_code, 200)
        conf2_data = res_conf2.get_json()
        self.assertTrue(conf2_data['newly_verified'])
        self.assertTrue(conf2_data['report']['is_verified'])
        self.assertEqual(conf2_data['report']['confirmations_count'], 2)

        db.session.refresh(self.user_a)
        db.session.refresh(self.user_c)
        self.assertEqual(self.user_c.points_balance, 10)
        self.assertEqual(self.user_a.points_balance, 75)

    def test_03_family_sos_alert_and_live_tracking(self):
        """Verifica el envío de alerta SOS Familiar por botón/voz y el enlace público de rastreo en vivo."""
        token_a = self._login('autor_vial@josepo.com')

        res_sos = self.client.post(
            '/api/gamification/sos/family-alert',
            headers={'Authorization': f'Bearer {token_a}'},
            json={
                'lat': 10.5012,
                'lng': -66.9145,
                'contact_name': 'Ana de Autor (Esposa)',
                'contact_phone': '+584129991122',
                'custom_message': 'Emergencia vial activada por comando de voz.',
                'triggered_via': 'VOICE_COMMAND'
            }
        )
        self.assertEqual(res_sos.status_code, 201)
        alert_info = res_sos.get_json()['alert']
        self.assertEqual(alert_info['triggered_via'], 'VOICE_COMMAND')
        self.assertIn('tracking_token', alert_info)

        # Verificar endpoint público de rastreo en vivo para el familiar
        tracking_token = alert_info['tracking_token']
        res_track = self.client.get(f'/api/gamification/sos/track/{tracking_token}')
        self.assertEqual(res_track.status_code, 200)
        track_data = res_track.get_json()['tracking']
        self.assertEqual(track_data['contact_name'], 'Ana de Autor (Esposa)')
        self.assertAlmostEqual(track_data['position']['lat'], 10.5012, places=4)

    def test_04_closure_hardening_postgres_cors_limiter_and_fx_cron(self):
        """Prueba de cierre integral: PostgreSQL+PostGIS, CORS restrictivo, Flask-Limiter, Esquemas y Cron BCV."""
        # 1. PostgreSQL + PostGIS reemplaza a josepo_dev.db en BaseConfig y ProductionConfig
        self.assertTrue(BaseConfig.POSTGRES_DATABASE_URI.startswith('postgresql://'))
        self.assertTrue(ProductionConfig.SQLALCHEMY_DATABASE_URI.startswith('postgresql://'))
        self.assertTrue(BaseConfig.POSTGIS_ENABLED)
        self.assertNotIn('josepo_dev.db', BaseConfig.POSTGRES_DATABASE_URI)

        # 2. Cabeceras CORS restrictivas (sin '*') y cabeceras OWASP
        res_allowed = self.client.get('/api/currency/rate', headers={'Origin': 'https://app.josepo.ve'})
        self.assertEqual(res_allowed.status_code, 200)
        self.assertEqual(res_allowed.headers.get('Access-Control-Allow-Origin'), 'https://app.josepo.ve')
        self.assertEqual(res_allowed.headers.get('X-Content-Type-Options'), 'nosniff')
        self.assertEqual(res_allowed.headers.get('X-Frame-Options'), 'SAMEORIGIN')

        res_blocked_origin = self.client.get('/api/currency/rate', headers={'Origin': 'https://attacker-evil.com'})
        self.assertNotEqual(res_blocked_origin.headers.get('Access-Control-Allow-Origin'), 'https://attacker-evil.com')
        self.assertNotEqual(res_blocked_origin.headers.get('Access-Control-Allow-Origin'), '*')

        # 3. Validación de esquemas bloquea XSS y payloads inválidos
        res_xss = self.client.post('/api/auth/register', json={
            'email': 'xss@josepo.com',
            'password': 'Password123!',
            'full_name': '<script>alert("hack")</script>',
            'phone_number': '+584149998877'
        })
        self.assertEqual(res_xss.status_code, 400)

        # 4. Automatización Cambiaria BCV (Cronjob)
        sync_res = CurrencyService.sync_official_bcv_rate(force=True, custom_rate=Decimal('45.2500'), source_tag='BCV_CRON_TEST')
        self.assertAlmostEqual(sync_res['rate'], 45.25, places=2)
        cron_state = CurrencyService.start_exchange_rate_cron(self.app, interval_minutes=15)
        self.assertTrue(cron_state['is_running'])
        CurrencyService.stop_exchange_rate_cron()


if __name__ == '__main__':
    unittest.main()
