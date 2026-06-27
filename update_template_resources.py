import os

filepath = 'templates/learning_outcome.html'
with open(filepath, 'r') as f:
    content = f.read()

search_text = """        <div class="card mb-3">
            <div class="card-body">
                <h5 class="card-title">Adaptive Notes</h5>
                <p>{{ lo.notes }}</p>
            </div>
        </div>

        <div class="card mb-3">
            <div class="card-body">
                <h5 class="card-title">Worked Examples</h5>
                <p>{{ lo.examples }}</p>
            </div>
        </div>"""

replace_text = """        {% if resources %}
            {% for resource in resources %}
            <div class="card mb-3 border-primary shadow-sm">
                <div class="card-body">
                    <h5 class="card-title text-primary">{{ resource.title }} <small class="text-muted">({{ resource.type }})</small></h5>
                    <p>{{ resource.content }}</p>
                </div>
            </div>
            {% endfor %}
        {% else %}
            <div class="card mb-3">
                <div class="card-body">
                    <h5 class="card-title">Learning Materials</h5>
                    <p>{{ lo.notes }}</p>
                </div>
            </div>
        {% endif %}"""

content = content.replace(search_text, replace_text)

with open(filepath, 'w') as f:
    f.write(content)
print("Template updated for adaptive resources.")
