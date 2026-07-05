import pytest
from app import app
from models import db, User, Role

@pytest.fixture
def client():
    app.config['TESTING'] = True
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
    with app.app_context():
        db.create_all()
        # Seed basic roles if they don't exist
        for r_name in ['learner', 'teacher', 'super_admin']:
            existing = db.session.query(Role).filter_by(role_name=r_name).first()
            if not existing:
                role = Role(role_name=r_name, display_name=r_name.replace('_', ' ').title())
                db.session.add(role)
        db.session.commit()
        yield app.test_client()

def test_home_page_redirect(client):
    response = client.get('/')
    assert response.status_code == 302 # Should redirect to login
