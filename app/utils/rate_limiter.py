import time
import threading
from collections import defaultdict, deque


class SlidingWindowRateLimiter:
    """
    Rate Limiter Thread-Safe basado en Ventana Deslizante (Hallazgo D).
    Protege endpoints críticos (OTP, Auth) contra fuerza bruta y abuso automatizado por IP o teléfono.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._buckets = defaultdict(deque)

    def is_allowed(self, key: str, max_requests: int, window_seconds: int) -> tuple[bool, int]:
        """
        Verifica si la clave `key` puede realizar una petición dentro de la ventana.
        Retorna (permitido: bool, retry_after_seconds: int).
        """
        now = time.monotonic()
        cutoff = now - window_seconds

        with self._lock:
            dq = self._buckets[key]
            while dq and dq[0] <= cutoff:
                dq.popleft()

            if len(dq) >= max_requests:
                retry_after = max(1, int(window_seconds - (now - dq[0])))
                return False, retry_after

            dq.append(now)
            return True, 0

    def reset(self, key: str = None):
        """Limpia el estado del rate limiter (útil en suites de pruebas)."""
        with self._lock:
            if key is None:
                self._buckets.clear()
            else:
                self._buckets.pop(key, None)


# Instancias globales compartidas para protección de endpoints (Fase 7)
otp_rate_limiter = SlidingWindowRateLimiter()
auth_rate_limiter = SlidingWindowRateLimiter()

