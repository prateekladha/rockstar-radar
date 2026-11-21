"""Regression test for the unauthenticated liveness probe `GET /api/health`.

Uptime monitors and load balancers hit this endpoint directly (no session cookie),
so it must return 200 with exactly {"status": "ok"} and must never require auth
nor depend on DB/broker state.
"""
import os
import unittest

# The probe must work without any background jobs running, so keep import-time
# behaviour quiet for the test process (these are read by server.main's lifespan).
os.environ.setdefault('RADAR_SCHED', '0')
os.environ.setdefault('RADAR_ORDER_ENGINE', '0')

try:
    import fastapi  # noqa: F401
    import server.main  # noqa: F401
    _IMPORT_ERROR = None
except ImportError as e:  # pragma: no cover - deps not installed in this environment
    _IMPORT_ERROR = e


def _client():
    from fastapi.testclient import TestClient
    from server.main import app
    return TestClient(app)


@unittest.skipIf(_IMPORT_ERROR is not None, f'server deps unavailable: {_IMPORT_ERROR}')
class HealthEndpointTests(unittest.TestCase):
    def test_health_returns_ok_without_auth(self):
        # No cookies/headers at all: health must not require a logged-in user.
        r = _client().get('/api/health')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), {'status': 'ok'})

    def test_health_is_json_not_the_spa_shell(self):
        # The SPA fallback route (/{full_path:path}) is registered last; make sure the
        # JSON probe still wins and never returns the HTML shell.
        r = _client().get('/api/health')
        self.assertEqual(r.headers.get('content-type', '').split(';')[0], 'application/json')

    def test_health_route_is_registered(self):
        # Registered on the live app (visible in the generated OpenAPI schema) and
        # tagged so it shows up as an ops probe rather than product API surface.
        from server.main import app
        schema = app.openapi()
        self.assertIn('/api/health', schema['paths'])
        self.assertIn('get', schema['paths']['/api/health'])


if __name__ == '__main__':
    unittest.main()
