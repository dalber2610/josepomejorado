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
    def calculate_eta(distance_km: float, avg_speed_kmh: float = 35.0, is_road_distance: bool = False) -> dict:
        """
        Calcula el Tiempo Estimado de Llegada (ETA) dinámico en minutos y segundos
        a partir de la distancia restante. Disminuye proporcionalmente a medida que
        la grúa se acerca al punto de encuentro.
        """
        dist = max(0.0, float(distance_km or 0.0))
        if dist <= 0.03:
            return {
                'distance_km': 0.0,
                'road_distance_km': 0.0,
                'total_seconds': 0,
                'eta_minutes': 0,
                'eta_seconds': 0,
                'time_min': 0.0,
                'eta_formatted': '¡En el sitio! (0 min)',
                'arrived': True
            }

        road_dist = dist if is_road_distance else (dist * 1.22)
        speed = max(10.0, float(avg_speed_kmh or 35.0))
        total_seconds = max(5, int(round((road_dist / speed) * 3600.0)))
        eta_minutes = total_seconds // 60
        eta_seconds = total_seconds % 60

        if eta_minutes > 0:
            eta_formatted = f"{eta_minutes} min {eta_seconds:02d} seg"
        else:
            eta_formatted = f"{eta_seconds} seg (Llegando)"

        return {
            'distance_km': round(dist, 2),
            'road_distance_km': round(road_dist, 2),
            'total_seconds': total_seconds,
            'eta_minutes': eta_minutes,
            'eta_seconds': eta_seconds,
            'time_min': round(total_seconds / 60.0, 1),
            'eta_formatted': eta_formatted,
            'arrived': False
        }

    @staticmethod
    def _build_interpolated_road_geometry(start_lat: float, start_lng: float, end_lat: float, end_lng: float, steps: int = 16) -> list:
        """
        Genera una polilínea suave de múltiples puntos cuando los proveedores externos de ruteo
        no están accesibles (modo offline/contingencia), permitiendo animación fluida paso a paso.
        """
        import math
        points = []
        d_lat = end_lat - start_lat
        d_lng = end_lng - start_lng
        for i in range(steps + 1):
            t = i / float(steps)
            # Ligera curvatura tipo avenida urbana que converge en los extremos (sin(pi * t))
            curve_offset = math.sin(math.pi * t) * 0.08
            lat = start_lat + d_lat * t + (-d_lng * curve_offset)
            lng = start_lng + d_lng * t + (d_lat * curve_offset)
            points.append([round(lat, 6), round(lng, 6)])
        points[0] = [round(start_lat, 6), round(start_lng, 6)]
        points[-1] = [round(end_lat, 6), round(end_lng, 6)]
        return points

    @staticmethod
    def calculate_route(start_lat: float, start_lng: float, end_lat: float, end_lng: float) -> dict:
        """
        Calcula la ruta vial exacta calle por calle (polilínea GeoJSON), distancia vial
        y tiempo estimado de llegada (ETA) entre la grúa y el destino.
        Utiliza OSRM (OpenStreetMap Routing Machine) como motor principal sin requerir API Key,
        con respaldo a MapQuest Directions y geometría interpolada de contingencia.
        """
        straight_dist = GeoService.calculate_distance_km((start_lat, start_lng), (end_lat, end_lng))
        if straight_dist <= 0.03:
            eta_zero = GeoService.calculate_eta(0.0, is_road_distance=True)
            return {
                'distance_km': 0.0,
                'time_min': 0.0,
                'total_seconds': 0,
                'eta_minutes': 0,
                'eta_seconds': 0,
                'eta_formatted': eta_zero['eta_formatted'],
                'latlngs': [[round(start_lat, 6), round(start_lng, 6)], [round(end_lat, 6), round(end_lng, 6)]],
                'narrative': ["La unidad de grúa se encuentra en el sitio."]
            }

        # 1. Intentar ruteo vial exacto calle por calle mediante OSRM (OpenStreetMap)
        osrm_url = (
            f"https://router.project-osrm.org/route/v1/driving/"
            f"{start_lng},{start_lat};{end_lng},{end_lat}"
        )
        try:
            osrm_res = requests.get(
                osrm_url,
                params={
                    'overview': 'full',
                    'geometries': 'geojson',
                    'steps': 'true'
                },
                timeout=3.5
            )
            if osrm_res.status_code == 200:
                osrm_data = osrm_res.json()
                routes = osrm_data.get('routes', [])
                if routes:
                    best_route = routes[0]
                    coords = best_route.get('geometry', {}).get('coordinates', [])
                    if len(coords) >= 2:
                        # Convertir de GeoJSON [lng, lat] a formato Leaflet [lat, lng]
                        latlngs = [[round(pt[1], 6), round(pt[0], 6)] for pt in coords]
                        latlngs[0] = [round(start_lat, 6), round(start_lng, 6)]
                        latlngs[-1] = [round(end_lat, 6), round(end_lng, 6)]

                        road_dist_km = max(straight_dist, float(best_route.get('distance', 0.0)) / 1000.0)
                        eta_info = GeoService.calculate_eta(road_dist_km, avg_speed_kmh=35.0, is_road_distance=True)

                        narratives = []
                        for leg in best_route.get('legs', []):
                            for step in leg.get('steps', []):
                                street_name = step.get('name', '')
                                if street_name and street_name not in narratives:
                                    narratives.append(f"Avanzar por {street_name}")
                        if not narratives:
                            narratives = ["Ruta vial óptima trazada por OpenStreetMap."]

                        return {
                            'distance_km': round(road_dist_km, 2),
                            'time_min': eta_info['time_min'],
                            'total_seconds': eta_info['total_seconds'],
                            'eta_minutes': eta_info['eta_minutes'],
                            'eta_seconds': eta_info['eta_seconds'],
                            'eta_formatted': eta_info['eta_formatted'],
                            'latlngs': latlngs,
                            'narrative': narratives
                        }
        except Exception as osrm_err:
            logger.debug(f"OSRM no disponible temporalmente, usando respaldo: {osrm_err}")

        # 2. Respaldo opcional con MapQuest si posee API Key configurada
        api_key = None
        try:
            api_key = current_app.config.get('MAPQUEST_API_KEY')
        except RuntimeError:
            api_key = None

        if api_key:
            url = "https://www.mapquestapi.com/directions/v2/route"
            try:
                response = requests.get(
                    url,
                    params={
                        'key': api_key,
                        'from': f"{start_lat},{start_lng}",
                        'to': f"{end_lat},{end_lng}"
                    },
                    timeout=5
                )
                data = response.json()
                if data.get('route') and 'legs' in data['route']:
                    route = data['route']
                    legs = route.get('legs', [{}])[0]
                    maneuvers = legs.get('maneuvers', [])

                    latlngs = [[round(start_lat, 6), round(start_lng, 6)]]
                    narratives = []
                    for m in maneuvers:
                        pt = m.get('startPoint', {})
                        if 'lat' in pt and 'lng' in pt:
                            latlngs.append([round(pt['lat'], 6), round(pt['lng'], 6)])
                        if 'narrative' in m:
                            narratives.append(m['narrative'])

                    latlngs.append([round(end_lat, 6), round(end_lng, 6)])
                    road_dist_km = round(route['distance'] * 1.60934, 2)
                    eta_info = GeoService.calculate_eta(road_dist_km, avg_speed_kmh=35.0, is_road_distance=True)

                    return {
                        'distance_km': road_dist_km,
                        'time_min': eta_info['time_min'],
                        'total_seconds': eta_info['total_seconds'],
                        'eta_minutes': eta_info['eta_minutes'],
                        'eta_seconds': eta_info['eta_seconds'],
                        'eta_formatted': eta_info['eta_formatted'],
                        'latlngs': latlngs,
                        'narrative': narratives
                    }
            except Exception as e:
                logger.warning(f"Error calculando ruta con MapQuest: {e}")

        # 3. Respaldo determinístico multipunto (sin conexión externa)
        eta_info = GeoService.calculate_eta(straight_dist, avg_speed_kmh=35.0, is_road_distance=False)
        fallback_latlngs = GeoService._build_interpolated_road_geometry(start_lat, start_lng, end_lat, end_lng)
        return {
            'distance_km': eta_info['road_distance_km'],
            'time_min': eta_info['time_min'],
            'total_seconds': eta_info['total_seconds'],
            'eta_minutes': eta_info['eta_minutes'],
            'eta_seconds': eta_info['eta_seconds'],
            'eta_formatted': eta_info['eta_formatted'],
            'latlngs': fallback_latlngs,
            'narrative': ["Ruta vial estimada hacia el punto de asistencia."]
        }
