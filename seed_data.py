"""
Script para inicializar la base de datos y cargar datos semilla de prueba:
- 1 Usuario Administrador
- 1 Usuario Cliente de prueba (con puntos iniciales y contacto SOS familiar)
- 5 Choferes de grúa con sus unidades iniciales (Caracas, Maracay, Valencia, Puerto Ordaz)
- Catálogo de Talleres/Comercios Aliados y Reporte Vial Inicial para Validación Cruzada (Fase 5)
"""
from sqlalchemy import text
from app import create_app
from app.extensions import db
from app.models import (
    User, UserRole, TowTruck, TowRequest, TrafficReport, TrafficReportType,
    ExchangeRateLog, OtpVerification, Payment, ServiceContract,
    PartnerReward, PointTransaction, RewardRedemption, FamilySosAlert
)
from app.services.gamification_service import GamificationService
from decimal import Decimal


def _migrate_sqlite_columns_if_needed():
    """Agrega columnas nuevas de Fases 3, 4 y 5 a tablas existentes en SQLite local sin perder datos."""
    alter_statements = [
        "ALTER TABLE tow_requests ADD COLUMN payment_status VARCHAR(20) DEFAULT 'UNPAID' NOT NULL;",
        "ALTER TABLE users ADD COLUMN points_balance INTEGER DEFAULT 0 NOT NULL;",
        "ALTER TABLE users ADD COLUMN lifetime_points INTEGER DEFAULT 0 NOT NULL;",
        "ALTER TABLE users ADD COLUMN reputation_level VARCHAR(30) DEFAULT 'BRONCE' NOT NULL;",
        "ALTER TABLE users ADD COLUMN emergency_contact_name VARCHAR(100);",
        "ALTER TABLE users ADD COLUMN emergency_contact_phone VARCHAR(25);",
        "ALTER TABLE traffic_reports ADD COLUMN confirmations_count INTEGER DEFAULT 0 NOT NULL;",
        "ALTER TABLE traffic_reports ADD COLUMN confirmed_by_user_ids JSON DEFAULT '[]' NOT NULL;",
    ]
    for stmt in alter_statements:
        try:
            db.session.execute(text(stmt))
            db.session.commit()
        except Exception:
            db.session.rollback()


def seed_database():
    app = create_app('development')
    with app.app_context():
        print("[*] Creando tablas y verificando columnas en base de datos...")
        db.create_all()
        _migrate_sqlite_columns_if_needed()

        # 1. Crear Tasa Inicial de Contingencia si no existe
        if not ExchangeRateLog.query.first():
            print("[+] Sembrando tasa de cambio inicial...")
            rate_log = ExchangeRateLog(rate=Decimal('42.5000'), source='BCV_SEED')
            db.session.add(rate_log)

        # 2. Crear Usuario Administrador
        admin = User.query.filter_by(email='admin@josepo.com').first()
        if not admin:
            print("[+] Creando administrador...")
            admin = User(
                email='admin@josepo.com',
                full_name='Admin Josepo',
                phone_number='+584120000001',
                role=UserRole.ADMIN,
                points_balance=250,
                lifetime_points=250,
                reputation_level='PLATA'
            )
            admin.set_password('AdminPass2026!')
            db.session.add(admin)

        # 3. Crear Cliente de Prueba
        client = User.query.filter_by(email='cliente@ejemplo.com').first()
        if not client:
            print("[+] Creando usuario cliente de prueba...")
            client = User(
                email='cliente@ejemplo.com',
                full_name='Juan Conductor',
                phone_number='+584140000002',
                role=UserRole.CLIENT,
                points_balance=120,
                lifetime_points=120,
                reputation_level='PLATA',
                emergency_contact_name='María Pérez (Esposa)',
                emergency_contact_phone='+584129998877'
            )
            client.set_password('Cliente2026!')
            db.session.add(client)
        else:
            if (client.points_balance or 0) == 0:
                client.points_balance = 120
                client.lifetime_points = 120
                client.recalculate_reputation_level()
            if not client.emergency_contact_phone:
                client.emergency_contact_name = 'María Pérez (Esposa)'
                client.emergency_contact_phone = '+584129998877'

        db.session.commit()

        # 4. Flota Inicial de Grúas con sus choferes
        initial_fleet = [
            {'plate': 'GRU-001', 'model': 'Ford F-350 Plataforma', 'lat': 10.5000, 'lng': -66.9167, 'city': 'Caracas Centro', 'phone': '+584121110001'},
            {'plate': 'GRU-002', 'model': 'Chevrolet C-30 Gancho', 'lat': 10.2440, 'lng': -67.5970, 'city': 'Maracay', 'phone': '+584121110002'},
            {'plate': 'GRU-003', 'model': 'Iveco Eurocargo Plataforma', 'lat': 10.1800, 'lng': -68.0039, 'city': 'Valencia', 'phone': '+584121110003'},
            {'plate': 'GRU-004', 'model': 'Ford Super Duty Pesada', 'lat': 8.3409, 'lng': -62.6440, 'city': 'Puerto Ordaz', 'phone': '+584121110004'},
            {'plate': 'GRU-005', 'model': 'Dodge RAM 4000 Auxilio', 'lat': 10.4682, 'lng': -66.9966, 'city': 'Caracas Oeste', 'phone': '+584121110005'}
        ]

        first_driver = None
        for i, item in enumerate(initial_fleet, start=1):
            driver_email = f"chofer{i}@josepo.com"
            driver = User.query.filter_by(email=driver_email).first()
            if not driver:
                print(f"[+] Creando chofer {i} ({item['city']})...")
                driver = User(
                    email=driver_email,
                    full_name=f"Chofer Unidad {i}",
                    phone_number=item['phone'],
                    role=UserRole.DRIVER,
                    points_balance=150 * i,
                    lifetime_points=150 * i
                )
                driver.recalculate_reputation_level()
                driver.set_password('ChoferPass2026!')
                db.session.add(driver)
                db.session.commit()
            elif (driver.lifetime_points or 0) == 0:
                driver.points_balance = 150 * i
                driver.lifetime_points = 150 * i
                driver.recalculate_reputation_level()
                db.session.commit()

            if i == 1:
                first_driver = driver

            truck = TowTruck.query.filter_by(license_plate=item['plate']).first()
            if not truck:
                print(f"[+] Registrando grúa {item['plate']} ({item['model']})...")
                truck = TowTruck(
                    license_plate=item['plate'],
                    brand_model=item['model'],
                    driver_id=driver.id,
                    current_lat=item['lat'],
                    current_lng=item['lng'],
                    is_available=True,
                    is_active=True
                )
                db.session.add(truck)

        db.session.commit()

        # 5. Fase 5: Inicializar Catálogo de Talleres y Comercios Aliados
        GamificationService.ensure_default_catalog()

        # 6. Fase 5: Crear un reporte vial comunitario de otro usuario para probar Validación Cruzada
        if TrafficReport.query.count() == 0 and first_driver:
            demo_report = TrafficReport(
                author_id=first_driver.id,
                lat=10.5045,
                lng=-66.9120,
                report_type=TrafficReportType.ACCIDENT,
                description='Colisión leve en Autopista Francisco Fajardo sentido Este, canal rápido lento.',
                is_verified=False,
                confirmations_count=1,
                confirmed_by_user_ids=[admin.id]
            )
            db.session.add(demo_report)
            db.session.commit()

        print("\n[OK] Datos iniciales y Fase 5 (Gamificación, Talleres Aliados y SOS) cargados con éxito.")


if __name__ == '__main__':
    seed_database()
