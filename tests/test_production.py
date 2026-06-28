import unittest
import os
from app import app, db
from models import User

class TestProduction(unittest.TestCase):
    def setUp(self):
        app.config['TESTING'] = True
        app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
        app.config['WTF_CSRF_ENABLED'] = False
        app.config['DEBUG'] = True
        self.client = app.test_client()
        with app.app_context():
            db.create_all()

    def tearDown(self):
        with app.app_context():
            db.session.remove()
            db.drop_all()

    def test_404_handler(self):
        response = self.client.get('/this-route-does-not-exist')
        self.assertEqual(response.status_code, 404)
        self.assertIn(b'404', response.data)

    def test_index_redirects_to_login(self):
        response = self.client.get('/')
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.location.endswith('/login') or '/login' in response.location)

    def test_sync_endpoint_auth(self):
        response = self.client.post('/sync/assessments', json={'attempts': []})
        self.assertEqual(response.status_code, 302)

if __name__ == '__main__':
    unittest.main()
