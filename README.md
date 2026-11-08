# 🚛 Josepo Mejorado - Plataforma Integral de Despacho, Pagos Escrow, SLA, Gamificación y Centro de Control de Grúas

> **Fases 1, 2, 3, 4, 5, 6 y 7 (Blindaje y Paso a Producción) Completadas:**  
> Arquitectura de Producción, PostgreSQL 16 + PostGIS 3.4, Despacho Bidireccional SLA 30s, Telemetría GPS en Vivo Anti-Spoofing, Seguridad MFA/OTP con `Flask-Limiter`, CORS Restrictivo y Validación de Esquemas, Pasarela Pago Móvil Escrow, Contratos Digitales SHA-256, Centro de Control de Operaciones (`/admin`), Gamificación con Talleres Aliados, Botón SOS Familiar por Voz, App Móvil Flutter con GPS en Segundo Plano y Cronjob de Automatización Cambiaria BCV.

---

## 🎯 1. Resumen Ejecutivo por Fases

| Fase | Componente | Descripción de la Solución Implementada |
| :---: | :--- | :--- |
| **Fase 1** | **Persistencia & Seguridad** | Base de datos relacional SQLAlchemy, eliminación de claves en código plano, asignación atómica con bloqueo de filas (`SELECT FOR UPDATE`), montos enteros en centavos y JWT. |
| **Fase 2** | **Despacho & Telemetría** | Despacho bidireccional con **SLA de 30s y rotación automática** a la siguiente grúa más cercana. Telemetría GPS nativa (`watchPosition`) con filtro cinemático Anti-Spoofing ($\le$ 180 km/h), consolas web PWA (`/driver`, `/client`) y app en Flutter (`driver_mobile_flutter/`). |
| **Fase 3** | **Seguridad & Pagos Escrow** | Autenticación telefónica de emergencia **SMS / WhatsApp OTP (6 dígitos)** con revocación al 3er fallo y Rate Limiter. Pasarela de **Pago Móvil con Escrow retenido**, prevención de Parameter Tampering y división exacta 85% chofer / 15% Josepo. |
| **Fase 4** | **Contratos Digitales & Admin Hub** | **Acta digital de inspección vehicular** (placa, modelo, daños previos) con hash criptográfico SHA-256 para aseguradoras. **Auditoría de SLA** ($\le$ 30 min) y **Centro de Control de Operaciones (`/admin`)** con KPIs en vivo. |
| **Fase 5** | **Engagement, Gamificación & SOS** | **Sistema de Puntos y Niveles de Reputación Vial** (`BRONCE`, `PLATA`, `ORO`, `GUARDIÁN VIAL`, `LEYENDA VIAL`), catálogo de **Talleres y Comercios Aliados** para canje de cupones, **Validación Cruzada de Tráfico** y **Botón SOS Familiar + Comandos de Voz (Web Speech API)** con enlace de rastreo en vivo. |
| **Fase 6** | **Completitud App Móvil Flutter** | **Arquitectura modular de 4 pantallas** (`login_screen.dart`, `home_map_screen.dart`, `wallet_screen.dart`, `profile_screen.dart`) y **GPS en Segundo Plano Nativo** (`flutter_background_service` + `geolocator` con Foreground Service en Android e `Info.plist` `UIBackgroundModes` en iOS). |
| **Fase 7** | **Blindaje (Hardening) & Producción** | **Migración a PostgreSQL 16 + PostGIS 3.4** (`docker-compose.yml`, `scripts/init_postgis.sql`, reemplazo de `josepo_dev.db`), **Protección de Endpoints** con `Flask-Limiter`, **CORS restrictivo** y cabeceras OWASP en `extensions.py`, **Validación de Esquemas JSON** (`schema_validator.py`), **Cronjob de Automatización Cambiaria BCV** (`currency_service.py` y `scripts/cron_update_bcv.py`) y **Suites de Cierre (`test_phase5.py` y `test_phase7.py`)**. |

---

## 📂 2. Estructura Completa del Proyecto

```text
Josepo mejorado/
├── .env.example                  # Plantilla de variables de entorno seguras
├── .gitignore                    # Protección contra subida de secretos y base de datos
├── docker-compose.yml            # PostgreSQL 16 con PostGIS y Redis
├── requirements.txt              # Dependencias de Python optimizadas para Windows
├── run.py                        # Punto de entrada del servidor
├── seed_data.py                  # Carga de tablas, 5 grúas, talleres aliados y usuarios demo
├── README.md                     # Documentación técnica completa
├── tests/
│   ├── test_phase3.py            # Pruebas de OTP y Pagos Escrow
│   ├── test_phase4.py            # Pruebas de Contratos Digitales, SLA y Admin KPIs
│   ├── test_phase5.py            # Pruebas de Gamificación, Validación Cruzada y SOS Familiar
│   ├── test_phase6.py            # Pruebas de Arquitectura Flutter y GPS en Segundo Plano
│   └── test_security_audit.py    # Pruebas de los 5 hallazgos de auditoría de seguridad
├── app/
│   ├── __init__.py               # Application Factory, rutas /driver, /client y /admin
│   ├── config.py                 # Configuración por entornos (Dev, Prod, Test)
│   ├── extensions.py             # Instancias de SQLAlchemy, JWT, SocketIO, CORS
│   ├── models/                   # Modelos de base de datos
│   │   ├── user.py               # Usuarios, puntos, reputación y contacto SOS
│   │   ├── tow_truck.py          # Flota de grúas y telemetría GPS
│   │   ├── tow_request.py        # Pedidos con estatus de servicio y garantía
│   │   ├── traffic_report.py     # Reportes comunitarios y validación cruzada
│   │   ├── exchange_rate.py      # Auditoría y caché de tasas cambiarias
│   │   ├── otp_verification.py   # Códigos OTP de 6 dígitos con hash y expiración
│   │   ├── payment.py            # Pagos en centavos, split 85/15 y estados Escrow
│   │   ├── service_contract.py   # Actas de inspección, firmas SHA-256 y auditoría SLA
│   │   └── reward.py             # Talleres aliados, historial de puntos y cupones
│   ├── services/                 # Lógica de negocio pura
│   │   ├── geo_service.py        # Rutas, distancias geodésicas y filtro Anti-Spoofing
│   │   ├── currency_service.py   # Tipo de cambio BCV con Decimal
│   │   ├── dispatch_service.py   # Motor de despacho con SLA y enlace con Escrow
│   │   ├── otp_service.py        # Generación segura y envío de OTP (SMS / WhatsApp)
│   │   ├── payment_service.py    # Directorio de 22 bancos venezolanos y lógica Escrow
│   │   ├── contract_service.py   # Actas de inspección, SLA y sellos de aseguradora
│   │   ├── gamification_service.py # Motor de puntos, niveles y canjes en talleres
│   │   ├── notification_service.py # Alertas SOS familiares con enlace en vivo
│   │   └── admin_service.py      # Business Intelligence, KPIs y radar de flota
│   ├── api/                      # Endpoints REST
│   │   ├── auth_routes.py        # /api/auth (registro, login JWT)
│   │   ├── otp_routes.py         # /api/auth/otp (código SOS SMS / WhatsApp)
│   │   ├── payment_routes.py     # /api/payments (bancos, registro pago móvil, webhook)
│   │   ├── contract_routes.py    # /api/contracts (inspección, calificaciones, verificación)
│   │   ├── gamification_routes.py # /api/gamification (perfil, talleres, canjes, SOS)
│   │   ├── admin_routes.py       # /api/admin (kpis, monitoreo de flota, operaciones)
│   │   ├── driver_routes.py      # /api/driver (turno, telemetría, aceptación de ofertas)
│   │   ├── geo_routes.py         # /api/geo (geocoding, rutas)
│   │   ├── tow_routes.py         # /api/tows (cotización, solicitud de auxilio)
│   │   ├── traffic_routes.py     # /api/traffic (reportes de incidentes y confirmaciones)
│   │   └── currency_routes.py    # /api/currency (tasa de cambio)
│   ├── sockets/
│   │   └── events.py             # WebSockets en tiempo real con validación JWT
│   └── templates/
│       ├── driver.html           # Consola Móvil Web PWA para el Conductor
│       ├── client.html           # Interfaz de Auxilio Vial con OTP, SOS Voz y Gamificación
│       └── admin.html            # Centro de Control de Operaciones y SLA (Bento Grid)
└── driver_mobile_flutter/        # Proyecto Flutter Nativo para Operadores de Grúa
    ├── pubspec.yaml              # geolocator, flutter_background_service, flutter_map, etc.
    ├── android/app/src/main/AndroidManifest.xml # Permisos BACKGROUND_LOCATION y FOREGROUND_SERVICE
    ├── ios/Runner/Info.plist     # UIBackgroundModes (location, fetch, processing)
    └── lib/
        ├── main.dart             # Inicialización Background Service y restauración JWT
        ├── core/
        │   ├── constants.dart    # Variables --dart-define y paleta Midnight/Slate/Emerald
        │   ├── api_service.dart  # Cliente HTTP REST centralizado
        │   ├── socket_service.dart # WebSockets + Stream GPS Android/iOS Background
        │   └── background_location_service.dart # Isolate nativo con Foreground Notification
        └── screens/
            ├── login_screen.dart    # Login por Unidad/Clave y OTP SMS/WhatsApp 6 dígitos
            ├── home_map_screen.dart # Mapa FlutterMap, SLA 30s, 4 etapas, Inspección SHA-256 y Waze
            ├── wallet_screen.dart   # Billetera Escrow 85/15 en centavos, BCV y Pago Móvil
            └── profile_screen.dart  # Perfil de unidad, Permisos GPS Always-On y Club Guardián Vial
```

---

## 📋 3. Innovaciones de la Fase 4

### A. Acta Digital de Inspección Vehicular y Protección Legal
- Al hacer contacto la grúa con el vehículo accidentado, el chofer registra la **placa, modelo, color y notas de daños previos / rayones existentes**.
- Se estampa una **firma digital criptográfica (Hash SHA-256)** que certifica el estado del auto antes de ser cargado a la plataforma.
- **Protección para Aseguradoras y Talleres:** Se genera un token único inmutable que permite verificar el comprobante público vía `GET /api/contracts/verify/<token>` para reclamos de pólizas de seguro (Mercantil Seguros, Seguros Caracas, Mapfre, etc.).

### B. Auditoría de SLA de Tiempo de Respuesta
- Meta de llegada estándar: **$\le$ 30 minutos**.
- El sistema audita la diferencia exacta de tiempo entre la creación de la llamada de auxilio y la llegada del operador, marcando si el SLA fue cumplido o excedido.

### C. Centro de Control de Operaciones (`/admin`)
- Dashboard estilo **Bento Grid** con diseño Midnight Blue / Slate / Emerald:
  - **Radar Nacional de Flotas:** Visualización geográfica de todas las unidades en Caracas, Maracay, Valencia, Puerto Ordaz, etc., identificando unidades disponibles (verde), en servicio (rojo) o fuera de turno (gris).
  - **KPIs de Negocio:** % de cumplimiento de SLA, tiempo promedio de respuesta, volumen bruto gestionado (USD y VES a tasa BCV) y fondos retenidos en Escrow.
  - **Bitácora de Despacho en Vivo:** Tabla con historial de servicios, estatus de garantía bancaria y acceso a las actas digitales.

---

## 🧪 4. Pruebas Automatizadas

Se ejecutan las 5 suites completas de pruebas (20 tests en total):

```powershell
cd "C:\Users\USUARIO\OneDrive\Desktop\Josepo mejorado"
.\venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py" -v
```
> **Resultado:** 100% de pruebas superadas (**20/20 OK**), validando OTP, retención en Escrow, división 85/15, prevención de doble gasto, actas de inspección vehicular, cálculo de SLA, gamificación, validación cruzada, alertas SOS familiares, auditoría de seguridad (A–E) y completitud de la App Móvil Flutter con GPS en segundo plano.

---

## 🚀 5. Cómo Probar la Plataforma Completa en Vivo

1. **Iniciar el Servidor:**
   ```powershell
   cd "C:\Users\USUARIO\OneDrive\Desktop\Josepo mejorado"
   .\venv\Scripts\python.exe run.py
   ```

2. **Abrir las 3 Vistas en tu Navegador:**
   - **Centro de Control de Operaciones:** 👉 [`http://localhost:5000/admin`](http://localhost:5000/admin)  
     *(Observa los KPIs de SLA, el radar de la flota y el volumen financiero en tiempo real).*
   - **Consola del Chofer:** 👉 [`http://localhost:5000/driver`](http://localhost:5000/driver)  
     *(Selecciona la unidad GRU-001 y pulsa Ingresar).*
   - **Interfaz del Cliente:** 👉 [`http://localhost:5000/client`](http://localhost:5000/client)  
     *(Inicia sesión con Contraseña o vía SOS SMS/WhatsApp OTP, solicita auxilio y registra el Pago Móvil).*

3. **Flujo de Rescate Completo:**
   - En la consola del chofer suena la **alarma con cuenta de 30s** y acepta.
   - En la consola del chofer, avanza a *"2. Llegué al sitio"*: se abre el formulario de **Inspección de Vehículo**, registra los daños previos y el sistema certifica el tiempo de SLA.
   - Avanza a *"Finalizar Servicio"*: se libera el pago de garantía en Escrow (85% para el chofer).
   - En la pantalla del cliente se abre el modal para **Calificar con 5 estrellas** y sellar el comprobante legal de remolque.
   - En el **Centro de Control (`/admin`)**, verás cómo las métricas de SLA y los ingresos financieros se actualizan en vivo.
