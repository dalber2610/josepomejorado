import unittest
import os
import sys
from decimal import Decimal

# Asegurar que el directorio raíz del proyecto esté en el path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app
from app.extensions import db
from app.models import User, UserRole, TowTruck, TowRequest, TowRequestStatus, ServiceContract, Payment, PaymentStatus
from app.services.contract_service import ContractService
from app.services.admin_service import AdminService

class TestPhase4ContractsAndSla(unittest.TestCase):
    def setUp(self):
        self.app = create_app('testing')
        self.app_context = self.app.app_context()
        self.app_context.push()
        db.create_all()

        # Crear usuarios de prueba
        self.client_user = User(
            email='client_p4@josepo.com',
            phone_number='+584147778899',
            full_name='Mariana Rivas',
            role=UserRole.CLIENT
        )
        self.client_user.set_password('Pass123!')
        db.session.add(self.client_user)

        self.driver_user = User(
            email='driver_p4@josepo.com',
            phone_number='+584126665544',
            full_name='Carlos Grúas',
            role=UserRole.DRIVER
        )
        self.driver_user.set_password('Pass123!')
        db.session.add(self.driver_user)
        db.session.commit()

        # Crear grúa
        self.truck = TowTruck(
            license_plate='GRU-P4-01',
            brand_model='Chevrolet C-30 Plataforma',
            driver_id=self.driver_user.id,
            current_lat=10.4900,
            current_lng=-66.8500,
            is_available=True,
            is_active=True
        )
        db.session.add(self.truck)
        db.session.commit()

        # Crear solicitud de auxilio vial
        self.tow_req = TowRequest(
            client_id=self.client_user.id,
            truck_id=self.truck.id,
            status=TowRequestStatus.IN_TRANSIT_TO_USER,
            origin_lat=10.4850,
            origin_lng=-66.8400,
            distance_to_user_km=1.8,
            trip_distance_km=4.2,
            total_distance_km=6.0,
            cost_ves_cents=80000,
            cost_usd_cents=2000,
            exchange_rate=Decimal('40.0000')
        )
        db.session.add(self.tow_req)
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    def test_vehicle_inspection_and_sla_audit(self):
        # 1. Registrar inspección vehicular en sitio
        contract = ContractService.register_vehicle_inspection(
            request_id=self.tow_req.id,
            driver_id=self.driver_user.id,
            vehicle_plate='AB123CD',
            vehicle_model='Toyota Yaris 2020',
            vehicle_color='Azul',
            pre_existing_damages='Rayón en guardabarro trasero derecho'
        )

        self.assertIsNotNone(contract)
        self.assertEqual(contract.vehicle_plate, 'AB123CD')
        self.assertEqual(contract.vehicle_model, 'Toyota Yaris 2020')
        self.assertTrue(contract.sla_met) # Cumplió meta <= 30 min
        self.assertIsNotNone(contract.reception_signature_hash)
        self.assertIsNotNone(contract.digital_receipt_token)

    def test_client_signature_and_rating(self):
        # 1. Crear contrato
        ContractService.register_vehicle_inspection(
            request_id=self.tow_req.id,
            driver_id=self.driver_user.id,
            vehicle_plate='AB123CD',
            vehicle_model='Toyota Yaris 2020'
        )

        # 2. Cliente califica con 5 estrellas y firma conformidad
        rated_contract = ContractService.client_sign_and_rate(
            request_id=self.tow_req.id,
            client_id=self.client_user.id,
            rating=5,
            feedback='Excelente servicio, llegó en 15 minutos y cuidó el carro.'
        )

        self.assertEqual(rated_contract.client_rating, 5)
        self.assertIn('Excelente', rated_contract.client_feedback)
        self.assertIsNotNone(rated_contract.delivery_signature_hash)
        self.assertIsNotNone(rated_contract.delivered_at)

        # 3. Comprobante público para aseguradoras
        token = rated_contract.digital_receipt_token
        certified_doc = ContractService.get_contract_by_token(token)
        self.assertIsNotNone(certified_doc)
        self.assertTrue(certified_doc['certified'])
        self.assertEqual(certified_doc['contract']['vehicle']['plate'], 'AB123CD')
        self.assertEqual(certified_doc['service_summary']['client'], 'Mariana Rivas')

    def test_admin_kpis_and_fleet_monitoring(self):
        # 1. Obtener KPIs del centro de control
        kpis = AdminService.get_dashboard_kpis()
        self.assertIn('fleet', kpis)
        self.assertIn('operations', kpis)
        self.assertIn('sla', kpis)
        self.assertIn('financials', kpis)

        # Verificar conteo de flota
        self.assertEqual(kpis['fleet']['total_units'], 1)
        self.assertEqual(kpis['fleet']['active_on_shift'], 1)

        # 2. Listar telemetría de flota
        fleet = AdminService.get_fleet_telemetry_live()
        self.assertEqual(len(fleet), 1)
        self.assertEqual(fleet[0]['license_plate'], 'GRU-P4-01')

if __name__ == '__main__':
    unittest.main()

