import os

filepath = 'templates/learning_outcome.html'
with open(filepath, 'r') as f:
    content = f.read()

search_text = """        <div class="card mb-3">
            <div class="card-body">
                <h5 class="card-title">Worked Examples</h5>
                <p>{{ lo.examples }}</p>
            </div>
        </div>
        {% endif %}"""

replace_text = """        <div class="card mb-3">
            <div class="card-body">
                <h5 class="card-title">Worked Examples</h5>
                <p>{{ lo.examples }}</p>
            </div>
        </div>

        <div class="card mb-3">
            <div class="card-body">
                <h5 class="card-title">Practical Evidence</h5>
                <p>Demonstrate your mastery by submitting practical evidence (e.g., photos of your work, links to projects, or a reflection).</p>
                <form action="{{ url_for('submit_evidence', lo_id=lo.id) }}" method="POST">
                    <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
                    <div class="mb-3">
                        <textarea name="content" class="form-control" rows="3" placeholder="Describe your evidence or paste a link..." required></textarea>
                    </div>
                    <button type="submit" class="btn btn-info">Submit Evidence</button>
                </form>
            </div>
        </div>
        {% endif %}"""

content = content.replace(search_text, replace_text)

with open(filepath, 'w') as f:
    f.write(content)
print("Template updated for evidence submission.")
