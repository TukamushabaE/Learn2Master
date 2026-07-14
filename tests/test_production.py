import unittest
from app import app

class TestProduction(unittest.TestCase):
    def setUp(self):
        app.config['TESTING'] = True
        app.config['WTF_CSRF_ENABLED'] = False
        app.config['DEBUG'] = True
        self.client = app.test_client()

    def test_404_handler(self):
        response = self.client.get('/this-route-does-not-exist')
        self.assertEqual(response.status_code, 404)
        self.assertIn(b'404', response.data)

    def test_index_redirects_to_login(self):
        response = self.client.get('/')
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.location.endswith('/login') or '/login' in response.location)

    def test_health_endpoint_checks_database(self):
        response = self.client.get('/health')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()['status'], 'healthy')

    def test_sync_endpoint_auth(self):
        response = self.client.post('/sync/assessments', json={'attempts': []})
        self.assertEqual(response.status_code, 302)

if __name__ == '__main__':
    unittest.main()
