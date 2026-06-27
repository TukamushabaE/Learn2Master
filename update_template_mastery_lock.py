import os

filepath = 'templates/learning_outcome.html'
with open(filepath, 'r') as f:
    content = f.read()

# This is a bit fragile but let's try to wrap the whole col-md-4 card
search_text = """    <div class="col-md-4">
        <div class="card bg-light">"""

replace_text = """    <div class="col-md-4">
        {% if not is_locked or current_user.role != 'student' %}
        <div class="card bg-light">"""

content = content.replace(search_text, replace_text)

# Add closing tag before closing div of col-md-4
content = content.replace("""                </form>
            </div>
        </div>
    </div>""", """                </form>
            </div>
        </div>
        {% endif %}
    </div>""")

with open(filepath, 'w') as f:
    f.write(content)
print("Template updated for mastery lock.")
