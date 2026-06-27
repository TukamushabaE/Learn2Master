import os

filepath = 'seed_data.py'
with open(filepath, 'r') as f:
    content = f.read()

search_text = """        db.session.add(lo3)

        db.session.commit()
        print("Data seeded successfully.")"""

replace_text = """        db.session.add(lo3)
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
        print("Data seeded successfully.")"""

if search_text in content:
    new_content = content.replace(search_text, replace_text)
    with open(filepath, 'w') as f:
        f.write(new_content)
    print("seed_data.py updated.")
else:
    print("Search text not found.")
