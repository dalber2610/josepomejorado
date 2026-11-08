from datetime import datetime, timezone
import requests
from geopy.distance import geodesic
from flask import current_app
import logging

logger = logging.getLogger(__name__)


class GeoService:
    """Servicio de geolocalización, rutas, cálculo de distancias y validación cinemática Anti-Spoofing."""

    DEFAULT_MAX_SPEED_KMH = 180.0

    @staticmethod
    def calculate_distance_km(point_a: tuple, point_b: tuple) -> float:
        """Calcula la distancia geodésica en kilómetros entre dos coordenadas (lat, lng)."""
        return float(geodesic(point_a, point_b).km)

    @classmethod
    def validate_kinematic_movement(
        cls,
        prev_lat: float,
        prev_lng: float,
        prev_timestamp: datetime,
        new_lat: float,
        new_lng: float,
        new_timestamp: datetime = None,
        max_speed_kmh: float = None
    ) -> tuple[bool, float, str]:
        """
        Mitigación Hallazgo E (Anti-GPS Spoofing / Detección de Teletransportación):
        Verifica que el desplazamiento entre la posición previa y la nueva posición
        sea físicamente posible para un vehículo terrestre (velocidad <= max_speed_kmh).
        Retorna: (es_valido: bool, velocidad_calculada_kmh: float, mensaje: str)
        """
        if not (-90.0 <= new_lat <= 90.0) or not (-180.0 <= new_lng <= 180.0):
            return False, 0.0, "Coordenadas fuera de rango geográfico terrestre válido."

        if prev_lat is None or prev_lng is None or prev_timestamp is None:
            return True, 0.0, "Posición inicial registrada."

        now = new_timestamp or datetime.now(timezone.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        if prev_timestamp.tzinfo is None:
            prev_timestamp = prev_timestamp.replace(tzinfo=timezone.utc)

        dist_km = cls.calculate_distance_km((prev_lat, prev_lng), (new_lat, new_lng))

        # Tolerancia para fluctuación normal de antena GPS en reposo o movimiento corto (< 350m)
        if dist_km <= 0.35:
            return True, 0.0, "Desplazamiento dentro de margen local."

        elapsed_seconds = max(1.0, (now - prev_timestamp).total_seconds())
        elapsed_hours = elapsed_seconds / 3600.0
        speed_kmh = dist_km / elapsed_hours

        if max_speed_kmh is None:
            try:
                max_speed_kmh = float(current_app.config.get('MAX_SPEED_KMH_ANTI_SPOOF', cls.DEFAULT_MAX_SPEED_KMH))
            except RuntimeError:
                max_speed_kmh = cls.DEFAULT_MAX_SPEED_KMH

        if speed_kmh > max_speed_kmh:
            msg = (
                f"Salto de coordenadas físicamente imposible detectado (Anti-Spoofing GPS): "
                f"{dist_km:.2f} km en {elapsed_seconds:.1f}s ({speed_kmh:.1f} km/h > límite {max_speed_kmh:.0f} km/h)."
            )
            logger.warning(f"🚨 [SECURITY ALERT - GPS SPOOFING] {msg}")
            return False, round(speed_kmh, 2), msg

        return True, round(speed_kmh, 2), "Movimiento cinemático válido."

    @staticmethod
    def geocode(address: str) -> dict:
        """Convierte una dirección en coordenadas (lat, lng)."""
        api_key = current_app.config.get('MAPQUEST_API_KEY')
        if not api_key:
            raise ValueError("MAPQUEST_API_KEY no está configurada en el servidor.")

        url = "https://www.mapquestapi.com/geocoding/v1/address"
        try:
            response = requests.get(
                url,
                params={'key': api_key, 'location': address},
                timeout=6
            )
            response.raise_for_status()
            data = response.json()
            
            results = data.get('results', [])
            if results and results[0].get('locations'):
                loc = results[0]['locations'][0]['latLng']
                return {'lat': loc['lat'], 'lng': loc['lng']}
            
            return None
        except requests.exceptions.RequestException as e:
            logger.error(f"Error en servicio de geocodificación: {e}")
            raise RuntimeError("Fallo en la comunicación con el proveedor de mapas.")

    @staticmethod
    def reverse_geocode(lat: float, lng: float) -> str:
        """Convierte coordenadas (lat, lng) en una dirección legible."""
        api_key = current_app.config.get('MAPQUEST_API_KEY')
        if not api_key:
            return f"Coord ({lat:.4f}, {lng:.4f})"

        url = "https://www.mapquestapi.com/geocoding/v1/reverse"
        try:
            response = requests.get(
                url,
                params={'key': api_key, 'location': f"{lat},{lng}"},
                timeout=6
            )
            response.raise_for_status()
            data = response.json()
            
            results = data.get('results', [])
            if results and results[0].get('locations'):
                loc = results[0]['locations'][0]
                street = loc.get('street', '').strip()
                city = loc.get('adminArea5', '').strip()
                state = loc.get('adminArea3', '').strip()
                
                parts = [p for p in [street, city, state] if p]
                return ", ".join(parts) if parts else f"Coord ({lat:.4f}, {lng:.4f})"
            
            return f"Coord ({lat:.4f}, {lng:.4f})"
        except requests.exceptions.RequestException as e:
            logger.warning(f"Error en geocodificación inversa: {e}")
            return f"Coord ({lat:.4f}, {lng:.4f})"

    @staticmethod
    def calculate_route(start_lat: float, start_lng: float, end_lat: float, end_lng: float) -> dict:
        """Calcula la ruta óptima, distancia y maniobras entre dos puntos."""
        api_key = current_app.config.get('MAPQUEST_API_KEY')
        
        if not api_key:
            straight_dist = GeoService.calculate_distance_km((start_lat, start_lng), (end_lat, end_lng))
            estimated_road_dist = straight_dist * 1.25
            estimated_minutes = (estimated_road_dist / 45.0) * 60.0
            return {
                'distance_km': round(estimated_road_dist, 2),
                'time_min': round(estimated_minutes, 1),
                'latlngs': [[start_lat, start_lng], [end_lat, end_lng]],
                'narrative': ["Ruta estimada por línea vial directa."]
            }

        url = "https://www.mapquestapi.com/directions/v2/route"
        try:
            response = requests.get(
                url,
                params={
                    'key': api_key,
                    'from': f"{start_lat},{start_lng}",
                    'to': f"{end_lat},{end_lng}"
                },
                timeout=8
            )
            data = response.json()
            
            if data.get('route') and 'legs' in data['route']:
                route = data['route']
                legs = route.get('legs', [{}])[0]
                maneuvers = legs.get('maneuvers', [])
                
                latlngs = []
                narratives = []
                for m in maneuvers:
                    pt = m.get('startPoint', {})
                    if 'lat' in pt and 'lng' in pt:
                        latlngs.append([pt['lat'], pt['lng']])
                    if 'narrative' in m:
                        narratives.append(m['narrative'])
                
                latlngs.append([end_lat, end_lng])
                
                return {
                    'distance_km': round(route['distance'] * 1.60934, 2),
                    'time_min': round(route['time'] / 60.0, 1),
                    'latlngs': latlngs,
                    'narrative': narratives
                }
            
            straight_dist = GeoService.calculate_distance_km((start_lat, start_lng), (end_lat, end_lng))
            return {
                'distance_km': round(straight_dist * 1.25, 2),
                'time_min': round((straight_dist * 1.25 / 45.0) * 60.0, 1),
                'latlngs': [[start_lat, start_lng], [end_lat, end_lng]],
                'narrative': ["Ruta aproximada."]
            }
        except Exception as e:
            logger.error(f"Error calculando ruta: {e}")
            straight_dist = GeoService.calculate_distance_km((start_lat, start_lng), (end_lat, end_lng))
            return {
                'distance_km': round(straight_dist * 1.25, 2),
                'time_min': round((straight_dist * 1.25 / 45.0) * 60.0, 1),
                'latlngs': [[start_lat, start_lng], [end_lat, end_lng]],
                'narrative': ["Ruta en modo contingencia."]
            }
