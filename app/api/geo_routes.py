from flask import Blueprint, request, jsonify
from app.services.geo_service import GeoService
import logging

logger = logging.getLogger(__name__)
geo_bp = Blueprint('geo_bp', __name__, url_prefix='/api/geo')

def validate_coordinates(lat, lng):
    """Valida rango numérico estricto de latitud (-90 a 90) y longitud (-180 a 180)."""
    try:
        lat = float(lat)
        lng = float(lng)
        if -90.0 <= lat <= 90.0 and -180.0 <= lng <= 180.0:
            return lat, lng
        return None, None
    except (TypeError, ValueError):
        return None, None

@geo_bp.route('/geocode', methods=['POST'])
def geocode():
    data = request.get_json() or {}
    address = data.get('address', '').strip()

    if not address or len(address) < 3:
        return jsonify({'error': 'Dirección requerida (mínimo 3 caracteres).'}), 400

    if len(address) > 200:
        return jsonify({'error': 'La dirección no puede exceder 200 caracteres.'}), 400

    try:
        coords = GeoService.geocode(address)
        if not coords:
            return jsonify({'error': 'No se encontraron coordenadas para la dirección ingresada.'}), 404
        return jsonify(coords), 200
    except Exception as e:
        logger.error(f"Error en geocode: {e}")
        return jsonify({'error': 'No fue posible procesar la geocodificación en este momento.'}), 500

@geo_bp.route('/reverse-geocode', methods=['POST'])
def reverse_geocode():
    data = request.get_json() or {}
    lat, lng = validate_coordinates(data.get('lat'), data.get('lng'))

    if lat is None or lng is None:
        return jsonify({'error': 'Coordenadas lat/lng inválidas o fuera de rango.'}), 400

    try:
        address = GeoService.reverse_geocode(lat, lng)
        return jsonify({'address': address}), 200
    except Exception as e:
        logger.error(f"Error en reverse_geocode: {e}")
        return jsonify({'error': 'No fue posible resolver la dirección.'}), 500

@geo_bp.route('/calculate-route', methods=['POST'])
def calculate_route():
    data = request.get_json() or {}
    start = data.get('start', {})
    end = data.get('end', {})

    start_lat, start_lng = validate_coordinates(start.get('lat'), start.get('lng'))
    end_lat, end_lng = validate_coordinates(end.get('lat'), end.get('lng'))

    if start_lat is None or start_lng is None or end_lat is None or end_lng is None:
        return jsonify({'error': 'Puntos de inicio y fin deben tener lat/lng válidas.'}), 400

    try:
        route_data = GeoService.calculate_route(start_lat, start_lng, end_lat, end_lng)
        return jsonify(route_data), 200
    except Exception as e:
        logger.error(f"Error en calculate_route: {e}")
        return jsonify({'error': 'Error calculando la ruta de traslado.'}), 500
