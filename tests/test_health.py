import unittest

from fastapi.testclient import TestClient

from server.main import app

client = TestClient(app)


class HealthTests(unittest.TestCase):
    def test_health_returns_ok(self):
        resp = client.get('/api/health')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {'status': 'ok'})


if __name__ == '__main__':
    unittest.main()
