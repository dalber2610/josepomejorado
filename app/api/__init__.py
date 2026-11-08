from app.api.auth_routes import auth_bp
from app.api.geo_routes import geo_bp
from app.api.tow_routes import tow_bp
from app.api.traffic_routes import traffic_bp
from app.api.currency_routes import currency_bp
from app.api.driver_routes import driver_bp
from app.api.otp_routes import otp_bp
from app.api.payment_routes import payment_bp
from app.api.contract_routes import contract_bp
from app.api.admin_routes import admin_bp
from app.api.gamification_routes import gamification_bp


def register_api_blueprints(app):
    """Registra todos los Blueprints de la API REST."""
    app.register_blueprint(auth_bp)
    app.register_blueprint(geo_bp)
    app.register_blueprint(tow_bp)
    app.register_blueprint(traffic_bp)
    app.register_blueprint(currency_bp)
    app.register_blueprint(driver_bp)
    app.register_blueprint(otp_bp)
    app.register_blueprint(payment_bp)
    app.register_blueprint(contract_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(gamification_bp)
