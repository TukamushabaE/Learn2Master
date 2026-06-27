import os

filepath = 'templates/learning_outcome.html'
with open(filepath, 'r') as f:
    content = f.read()

search_text = """    <div class="col-md-8">
        <h2>{{ lo.name }}</h2>"""

replace_text = """    <div class="col-md-8">
        {% if is_locked %}
        <div class="alert alert-warning">
            <h5>Locked Learning Outcome</h5>
            <p>You must achieve at least 85% mastery in all previous learning outcomes before accessing this one.</p>
            <a href="{{ url_for('view_subject', subject_id=lo.topic.subject_id) }}" class="btn btn-secondary">Return to Subject</a>
        </div>
        {% else %}
        <h2>{{ lo.name }}</h2>"""

# Close the if block at the end of col-md-8
content = content.replace(search_text, replace_text)
content = content.replace("""        <div class="card mb-3">
            <div class="card-body">
                <h5 class="card-title">Worked Examples</h5>
                <p>{{ lo.examples }}</p>
            </div>
        </div>
    </div>""", """        <div class="card mb-3">
            <div class="card-body">
                <h5 class="card-title">Worked Examples</h5>
                <p>{{ lo.examples }}</p>
            </div>
        </div>
        {% endif %}
    </div>""")

with open(filepath, 'w') as f:
    f.write(content)
print("Template updated.")
