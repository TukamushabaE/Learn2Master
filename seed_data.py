from flask import Flask
from models import db, User, Subject, Topic, LearningOutcome, LearningResource
from werkzeug.security import generate_password_hash

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///learn2master.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db.init_app(app)

def seed():
    with app.app_context():
        # Clear existing data if any (optional but good for testing)
        db.drop_all()
        db.create_all()

        # Seed Users
        users = [
            User(username='elijah', password_hash=generate_password_hash('12345'), role='student', school='Demo Secondary School'),
            User(username='teacher', password_hash=generate_password_hash('12345'), role='teacher', school='Demo Secondary School'),
            User(username='admin', password_hash=generate_password_hash('12345'), role='admin', school='System')
        ]
        db.session.add_all(users)

        # Seed Subjects
        physics = Subject(name='Physics')
        ict = Subject(name='ICT')
        db.session.add_all([physics, ict])
        db.session.commit()

        # Seed Physics Topic
        mechanics = Topic(subject_id=physics.id, name='Introduction to Mechanics', order=1)
        db.session.add(mechanics)
        db.session.commit()

        # Seed Learning Outcomes for Physics
        lo1 = LearningOutcome(
            topic_id=mechanics.id,
            name='Distance and Displacement',
            description='Understand the difference between distance and displacement.',
            order=1,
            notes='Distance is a scalar quantity, while displacement is a vector...',
            video_url='https://www.youtube.com/embed/placeholder1',
            examples='Example 1: A car moves 5km north...'
        )
        lo2 = LearningOutcome(
            topic_id=mechanics.id,
            name='Speed and Velocity',
            description='Distinguish between speed and velocity.',
            order=2,
            notes='Speed = distance/time. Velocity = displacement/time.',
            video_url='https://www.youtube.com/embed/placeholder2',
            examples='Example: Calculate the velocity of a sprinter...'
        )
        db.session.add_all([lo1, lo2])

        # Seed ICT Topic
        computing = Topic(subject_id=ict.id, name='Computer Systems', order=1)
        db.session.add(computing)
        db.session.commit()

        lo3 = LearningOutcome(
            topic_id=computing.id,
            name='Hardware Components',
            description='Identify major hardware components of a computer.',
            order=1,
            notes='CPU, RAM, Motherboard, Storage...',
            video_url='https://www.youtube.com/embed/placeholder3',
            examples='Look inside a system unit to see the RAM slots.'
        )
        db.session.add(lo3)
        db.session.commit()

        # Seed Adaptive Resources for LO1
        res1 = LearningResource(
            learning_outcome_id=lo1.id,
            type='notes',
            title='Introductory Notes',
            content='Foundational concepts for distance and displacement.',
            min_mastery=0.0,
            max_mastery=0.6
        )
        res2 = LearningResource(
            learning_outcome_id=lo1.id,
            type='video',
            title='Advanced Vectors Video',
            content='Deep dive into vector displacement for high mastery students.',
            min_mastery=0.6,
            max_mastery=1.0
        )
        db.session.add_all([res1, res2])

        db.session.commit()
        print("Data seeded successfully.")

if __name__ == "__main__":
    seed()
