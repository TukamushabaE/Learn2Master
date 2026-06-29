import sqlite3
from werkzeug.security import generate_password_hash

DB_NAME = "learn2master.db"
conn = sqlite3.connect(DB_NAME)
conn.row_factory = sqlite3.Row
cur = conn.cursor()


def get_id(query, params=()):
    row = cur.execute(query, params).fetchone()
    return row[0] if row else None


# Roles, school, class, users
learner_role = get_id("SELECT role_id FROM roles WHERE role_name='learner'")
teacher_role = get_id("SELECT role_id FROM roles WHERE role_name='teacher'")
school_admin_role = get_id("SELECT role_id FROM roles WHERE role_name='school_admin'")
super_admin_role = get_id("SELECT role_id FROM roles WHERE role_name='super_admin'")
school_id = get_id("SELECT school_id FROM schools WHERE school_name='Kigezi High School'")

cur.execute("INSERT OR IGNORE INTO classes (class_name, school_id) VALUES (?, ?)", ("Senior One", school_id))
class_id = get_id("SELECT class_id FROM classes WHERE class_name='Senior One'")
cur.execute("INSERT OR IGNORE INTO terms (term_name, sequence_order) VALUES (?, ?)", ("Term One", 1))
term_id = get_id("SELECT term_id FROM terms WHERE term_name='Term One'")

users = [
    ("Tukamushaba Elijah", "elijah", "elijah@example.com", "12345", learner_role, school_id, "Learner", 1),
    ("ICT Physics Teacher", "teacher", "teacher@example.com", "12345", teacher_role, school_id, "Teacher", 3),
    ("School Administrator", "admin", "admin@example.com", "12345", school_admin_role, school_id, "School Administrator", 4),
    ("System Owner", "superadmin", "superadmin@example.com", "12345", super_admin_role, school_id, "Super Administrator", 5),
]

for full_name, username, email, password, role_id, sid, title, security_level in users:
    cur.execute("""
        INSERT OR IGNORE INTO users
        (full_name, username, email, password_hash, role_id, school_id, title,
         account_status, security_level, approved_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, 'Active', ?, CURRENT_TIMESTAMP)
    """, (full_name, username, email, generate_password_hash(password), role_id, sid, title, security_level))

learner_id = get_id("SELECT user_id FROM users WHERE username='elijah'")
teacher_id = get_id("SELECT user_id FROM users WHERE username='teacher'")
cur.execute("INSERT OR IGNORE INTO enrollments (learner_id, class_id) VALUES (?, ?)", (learner_id, class_id))
cur.execute("""
    INSERT OR IGNORE INTO learner_profiles
    (learner_id, class_level, learning_style, learning_pace, preferred_support, ai_profile_summary)
    VALUES (?, 'Senior One', 'Adaptive / Mixed', 'Not yet classified', 'Notes, video, worked examples and guided practice',
            'Initial learner profile. The AI profile updates after pre-test, practice, reflection and post-test evidence.')
""", (learner_id,))

# Subjects
ict_subject = get_id("SELECT subject_id FROM subjects WHERE subject_name='ICT'")
physics_subject = get_id("SELECT subject_id FROM subjects WHERE subject_name='Physics'")
for subject_id in (ict_subject, physics_subject):
    cur.execute("""
        INSERT OR IGNORE INTO teacher_subject_assignments
        (teacher_id, subject_id, class_id, school_id, assigned_by)
        VALUES (?, ?, ?, ?, ?)
    """, (teacher_id, subject_id, class_id, school_id, get_id("SELECT user_id FROM users WHERE username='admin'")))

topics = [
    (ict_subject, "Introduction to ICT", "Senior One", "Uganda NCDC ICT syllabus", "Computer systems, ICT tools, applications, safety, and responsible use."),
    (physics_subject, "Measurements in Physics", "Senior One", "Uganda NCDC Physics syllabus", "Physical quantities, SI units, measuring instruments, accuracy, and recording measurements."),
]
for subject_id, title, level, source, desc in topics:
    cur.execute("""
        INSERT INTO topics (subject_id, term_id, topic_title, class_level, curriculum_source, topic_description)
        SELECT ?, ?, ?, ?, ?, ?
        WHERE NOT EXISTS (SELECT 1 FROM topics WHERE subject_id=? AND topic_title=? AND class_level=?)
    """, (subject_id, term_id, title, level, source, desc, subject_id, title, level))

ict_topic = get_id("SELECT topic_id FROM topics WHERE topic_title='Introduction to ICT'")
phy_topic = get_id("SELECT topic_id FROM topics WHERE topic_title='Measurements in Physics'")

strand_rows = [
    (ict_subject, "Computer Systems and ICT Tools", "Use ICT tools safely to process and communicate information."),
    (physics_subject, "Measurements and Practical Physics", "Use measurement evidence to solve real-world problems."),
]
for subject_id, strand_name, strand_description in strand_rows:
    cur.execute("""
        INSERT OR IGNORE INTO strands (subject_id, strand_name, strand_description)
        VALUES (?, ?, ?)
    """, (subject_id, strand_name, strand_description))

ict_strand = get_id("SELECT strand_id FROM strands WHERE strand_name='Computer Systems and ICT Tools'")
phy_strand = get_id("SELECT strand_id FROM strands WHERE strand_name='Measurements and Practical Physics'")
sub_strand_rows = [
    (ict_strand, "ICT concepts, tools and responsible use", "Information processing, tools, applications, safety and digital responsibility."),
    (phy_strand, "Physical quantities, units and measuring instruments", "SI units, instruments, precision, errors and practical investigation evidence."),
]
for strand_id, sub_name, sub_desc in sub_strand_rows:
    cur.execute("""
        INSERT OR IGNORE INTO sub_strands (strand_id, sub_strand_name, sub_strand_description)
        VALUES (?, ?, ?)
    """, (strand_id, sub_name, sub_desc))

ict_substrand = get_id("SELECT sub_strand_id FROM sub_strands WHERE sub_strand_name='ICT concepts, tools and responsible use'")
phy_substrand = get_id("SELECT sub_strand_id FROM sub_strands WHERE sub_strand_name='Physical quantities, units and measuring instruments'")

competencies = [
    (ict_subject, "ICT-S1-T1", "Introduction to ICT", "Senior One Term One: Computer Systems. Learners understand ICT, common ICT tools, computer applications, safety, and responsible use."),
    (physics_subject, "PHY-S1-T1", "Measurements in Physics", "Senior One Term One: Mechanics and Properties of Matter. Learners apply SI units, measuring instruments, accuracy, and recording of measurements."),
]
for subject_id, code, name, desc in competencies:
    cur.execute("""
        INSERT OR IGNORE INTO competencies
        (subject_id, competency_code, competency_name, competency_description)
        VALUES (?, ?, ?, ?)
    """, (subject_id, code, name, desc))

cur.execute("UPDATE competencies SET topic_id=?, sub_strand_id=? WHERE competency_code='ICT-S1-T1'", (ict_topic, ict_substrand))
cur.execute("UPDATE competencies SET topic_id=?, sub_strand_id=? WHERE competency_code='PHY-S1-T1'", (phy_topic, phy_substrand))

ict_comp = get_id("SELECT competency_id FROM competencies WHERE competency_code='ICT-S1-T1'")
phy_comp = get_id("SELECT competency_id FROM competencies WHERE competency_code='PHY-S1-T1'")

# One syllabus topic per subject
courses = [
    (ict_subject, ict_topic, "Introduction to ICT", "Senior One Term One topic from the NCDC ICT syllabus. Focus: ICT meaning, tools, applications, information processing, laboratory safety, and responsible use.", "Senior One"),
    (physics_subject, phy_topic, "Measurements in Physics", "Senior One Term One topic from the NCDC Physics syllabus. Focus: physical quantities, SI units, measuring instruments, accuracy, and practical recording of measurements.", "Senior One"),
]
for subject_id, topic_id, title, desc, level in courses:
    cur.execute("""
        INSERT INTO courses (subject_id, topic_id, course_title, course_description, difficulty_level)
        SELECT ?, ?, ?, ?, ?
        WHERE NOT EXISTS (SELECT 1 FROM courses WHERE subject_id=? AND course_title=?)
    """, (subject_id, topic_id, title, desc, level, subject_id, title))

ict_course = get_id("SELECT course_id FROM courses WHERE course_title='Introduction to ICT'")
phy_course = get_id("SELECT course_id FROM courses WHERE course_title='Measurements in Physics'")

# Sequential outcomes: LO2 stays locked until LO1 is mastered.
outcomes = [
    (ict_comp, "ICT-LO1", "Use ICT concepts to explain real communication tasks", "Explain ICT, data, information, communication and the information-processing cycle using real school, home and community examples.", 80, 1),
    (ict_comp, "ICT-LO2", "Select ICT tools for real-life fields and tasks", "Identify common ICT tools, match them to education, health, business, agriculture and communication tasks, and justify the selection.", 80, 2),
    (ict_comp, "ICT-LO3", "Use and maintain ICT tools to produce evidence", "Use selected ICT tools to capture, process, store and present information while handling equipment responsibly.", 80, 3),
    (ict_comp, "ICT-LO4", "Apply safe, healthy and responsible ICT practice", "Apply laboratory safety, healthy use, password protection, data respect, fault reporting and responsible ICT behaviour in practical settings.", 80, 4),
    (phy_comp, "PHY-LO1", "Measure and classify physical quantities using SI units", "Identify measurable quantities, distinguish fundamental and derived quantities, use SI units and record symbols correctly.", 80, 1),
    (phy_comp, "PHY-LO2", "Choose and use measuring instruments accurately", "Select instruments for length, mass, volume, time and temperature, read scales correctly and record measurements with suitable precision.", 80, 2),
    (phy_comp, "PHY-LO3", "Estimate and calculate area, volume and density", "Estimate and measure area, volume, mass and density, convert units and apply measurement results to real materials and spaces.", 80, 3),
    (phy_comp, "PHY-LO4", "Improve measurement reliability and reduce errors", "Identify sources of error, repeat measurements, calculate averages, avoid parallax and improve reliability of practical evidence.", 80, 4),
    (phy_comp, "PHY-LO5", "Plan fair tests and communicate measurement evidence", "Plan fair investigations, record data in tables, represent results in graphs, identify trends and justify conclusions using evidence.", 80, 5),
]
for item in outcomes:
    cur.execute("""
        INSERT OR IGNORE INTO learning_outcomes
        (competency_id, outcome_code, outcome_name, outcome_description, mastery_threshold, sequence_order)
        VALUES (?, ?, ?, ?, ?, ?)
    """, item)

cur.execute("UPDATE learning_outcomes SET topic_id=?, sub_strand_id=? WHERE competency_id=?", (ict_topic, ict_substrand, ict_comp))
cur.execute("UPDATE learning_outcomes SET topic_id=?, sub_strand_id=? WHERE competency_id=?", (phy_topic, phy_substrand, phy_comp))
cur.execute("UPDATE learning_outcomes SET practical_required=1 WHERE outcome_code IN ('ICT-LO3','ICT-LO4','PHY-LO2','PHY-LO3','PHY-LO4','PHY-LO5')")

generic_skill_rows = [
    ("Critical thinking and problem solving", "Learners investigate evidence, compare options and justify decisions."),
    ("Communication", "Learners explain methods, results and conclusions clearly."),
    ("Collaboration", "Learners work in pairs or groups to solve practical problems."),
    ("Creativity and innovation", "Learners design useful outputs, investigations and improvement plans."),
    ("ICT proficiency", "Learners use technology safely and productively."),
    ("Self-directed learning", "Learners monitor progress, reflect and act on feedback."),
]
for name, desc in generic_skill_rows:
    cur.execute("INSERT OR IGNORE INTO generic_skills (skill_name, skill_description) VALUES (?, ?)", (name, desc))

value_rows = [
    ("Responsibility", "Use equipment, data and shared spaces responsibly."),
    ("Integrity", "Report evidence honestly and acknowledge limitations."),
    ("Respect", "Respect peers, teachers, data privacy and school property."),
]
for name, desc in value_rows:
    cur.execute("INSERT OR IGNORE INTO curriculum_values (value_name, value_description) VALUES (?, ?)", (name, desc))

issue_rows = [
    ("Environmental awareness", "Use resources carefully and reduce waste."),
    ("Health and safety", "Protect learners, equipment and the learning environment."),
    ("Digital citizenship", "Use information and technology ethically."),
]
for name, desc in issue_rows:
    cur.execute("INSERT OR IGNORE INTO cross_cutting_issues (issue_name, issue_description) VALUES (?, ?)", (name, desc))

for outcome_code, indicator, criterion in [
    ("ICT-LO1", "Explains ICT terms using real communication examples.", "Identifies information, technology, communication and processing stages correctly."),
    ("ICT-LO2", "Selects ICT tools for school and community tasks.", "Justifies tool choice using task, user and safety requirements."),
    ("ICT-LO3", "Produces and stores practical ICT evidence safely.", "Creates usable evidence and explains how it was captured, processed and saved."),
    ("ICT-LO4", "Applies safe and responsible ICT behaviour.", "Identifies risks and chooses actions that protect people, data and equipment."),
    ("PHY-LO1", "Classifies measurable quantities and uses SI units.", "Records measurements with correct quantity, value, unit and symbol."),
    ("PHY-LO2", "Chooses and reads measuring instruments accurately.", "Selects a suitable instrument and records readings with suitable precision."),
    ("PHY-LO3", "Uses measurements to calculate area, volume or density.", "Applies correct formula, compatible units and real-world interpretation."),
    ("PHY-LO4", "Improves measurement reliability and reduces error.", "Repeats readings, averages results and explains how errors were controlled."),
    ("PHY-LO5", "Plans and communicates fair-test evidence.", "Controls variables, records data, graphs results and draws evidence-based conclusions."),
]:
    outcome_id = get_id("SELECT outcome_id FROM learning_outcomes WHERE outcome_code=?", (outcome_code,))
    cur.execute("""
        INSERT INTO performance_indicators (outcome_id, indicator_text)
        SELECT ?, ? WHERE NOT EXISTS (
            SELECT 1 FROM performance_indicators WHERE outcome_id=? AND indicator_text=?
        )
    """, (outcome_id, indicator, outcome_id, indicator))
    cur.execute("""
        INSERT INTO success_criteria (outcome_id, criteria_text)
        SELECT ?, ? WHERE NOT EXISTS (
            SELECT 1 FROM success_criteria WHERE outcome_id=? AND criteria_text=?
        )
    """, (outcome_id, criterion, outcome_id, criterion))
    for skill_name in ("Critical thinking and problem solving", "Communication", "Self-directed learning"):
        skill_id = get_id("SELECT skill_id FROM generic_skills WHERE skill_name=?", (skill_name,))
        cur.execute("INSERT OR IGNORE INTO outcome_generic_skills (outcome_id, skill_id) VALUES (?, ?)", (outcome_id, skill_id))
    value_id = get_id("SELECT value_id FROM curriculum_values WHERE value_name='Responsibility'")
    cur.execute("INSERT OR IGNORE INTO outcome_values (outcome_id, value_id) VALUES (?, ?)", (outcome_id, value_id))
    issue_name = "Digital citizenship" if outcome_code.startswith("ICT") else "Health and safety"
    issue_id = get_id("SELECT issue_id FROM cross_cutting_issues WHERE issue_name=?", (issue_name,))
    cur.execute("INSERT OR IGNORE INTO outcome_cross_cutting_issues (outcome_id, issue_id) VALUES (?, ?)", (outcome_id, issue_id))
    for level, score, description in [
        ("Beginning", 1, "Evidence is incomplete or needs major teacher support."),
        ("Developing", 2, "Evidence addresses the task but has gaps in accuracy or explanation."),
        ("Proficient", 3, "Evidence meets the success criteria with clear application."),
        ("Advanced", 4, "Evidence exceeds expectations and transfers the skill to a new context."),
    ]:
        cur.execute("""
            INSERT INTO rubric_criteria (outcome_id, criterion, description, level, score)
            SELECT ?, 'Practical application evidence', ?, ?, ?
            WHERE NOT EXISTS (
                SELECT 1 FROM rubric_criteria WHERE outcome_id=? AND criterion='Practical application evidence' AND level=?
            )
        """, (outcome_id, description, level, score, outcome_id, level))

lessons = [
    (ict_course, "ICT-LO1", "ICT Concepts in Real Communication", "Learners explain ICT through real tasks such as sending messages, preparing reports and sharing evidence. They connect data, information, technology and communication to the processing cycle.", 20),
    (ict_course, "ICT-LO2", "Selecting ICT Tools for Tasks", "Learners identify ICT tools, describe their characteristics and choose appropriate tools for education, health, agriculture, business and communication tasks.", 25),
    (ict_course, "ICT-LO3", "Using and Maintaining ICT Tools", "Learners use ICT tools to capture, process, save and present information while demonstrating careful handling, correct shutdown and basic maintenance habits.", 30),
    (ict_course, "ICT-LO4", "Safe and Responsible ICT Practice", "Learners apply computer laboratory safety, healthy posture, password care, responsible data use and fault reporting in practical ICT work.", 30),
    (phy_course, "PHY-LO1", "Physical Quantities, Units and Symbols", "Learners identify measurable physical quantities, classify them, use SI units and record values with correct symbols and conversions.", 30),
    (phy_course, "PHY-LO2", "Measuring Instruments and Scale Reading", "Learners choose suitable instruments, read scales at eye level, identify smallest divisions and record measurements with appropriate precision.", 35),
    (phy_course, "PHY-LO3", "Area, Volume, Mass and Density", "Learners estimate and measure area, volume and mass, calculate density and apply the measurements to real classroom and community materials.", 35),
    (phy_course, "PHY-LO4", "Errors, Repeated Readings and Reliability", "Learners identify measurement errors, repeat readings, calculate average values and explain how reliability improves.", 35),
    (phy_course, "PHY-LO5", "Fair Tests, Graphs and Measurement Evidence", "Learners plan fair tests, collect data, record tables, draw graphs, identify trends and make evidence-based conclusions.", 40),
]
for course_id, outcome_code, title, content, minutes in lessons:
    outcome_id = get_id("SELECT outcome_id FROM learning_outcomes WHERE outcome_code=?", (outcome_code,))
    cur.execute("""
        INSERT INTO lessons (course_id, outcome_id, lesson_title, lesson_content, video_url, estimated_minutes, sequence_order)
        SELECT ?, ?, ?, ?, ?, ?, 1
        WHERE NOT EXISTS (SELECT 1 FROM lessons WHERE outcome_id=? AND lesson_title=?)
    """, (course_id, outcome_id, title, content, "", minutes, outcome_id, title))

# Learning activities
activities = {
    "ICT-LO1": [
        ("Concept sorting", "Classify examples as data, information, hardware, software, input, process, storage, output, or communication.", "Practice"),
        ("Real-life ICT mapping", "List five ICT tools used at school and explain what information task each one performs.", "Reflection"),
    ],
    "ICT-LO2": [
        ("ICT tools walk-through", "Identify ICT tools in a computer laboratory and state one correct use for each.", "Practical"),
        ("Safety checklist", "Create a checklist of computer laboratory safety rules and explain why each rule matters.", "Reflection"),
    ],
    "ICT-LO3": [
        ("ICT evidence production", "Use a phone camera or computer to capture, save and describe evidence from a classroom task.", "Practical"),
        ("Tool maintenance routine", "Demonstrate safe startup, file saving, shutdown and basic care of an ICT tool.", "Demonstration"),
        ("Mini presentation task", "Prepare a short digital or paper presentation showing how the selected tool solved a real task.", "Presentation"),
    ],
    "ICT-LO4": [
        ("Laboratory risk map", "Identify safety risks in the ICT room and propose ways to prevent harm or equipment damage.", "Investigation"),
        ("Password and privacy case", "Read a scenario about shared passwords or exposed files and decide the responsible action.", "Case Study"),
        ("Healthy use checklist", "Create and apply a posture, breaks, lighting and device-care checklist during ICT practice.", "Self Assessment"),
    ],
    "PHY-LO1": [
        ("Unit matching", "Match physical quantities to their SI units and symbols.", "Practice"),
        ("Measurement diary", "Record five measurements around the classroom and write the correct units.", "Practical"),
    ],
    "PHY-LO2": [
        ("Instrument selection", "Choose the best instrument for measuring length, mass, volume, time, and temperature.", "Practice"),
        ("Scale reading practical", "Read sample scales and record values with correct units.", "Practical"),
    ],
    "PHY-LO3": [
        ("Area and volume survey", "Measure classroom objects and calculate area or volume for a real use such as covering, storing or arranging.", "Practical"),
        ("Density comparison", "Measure mass and volume of available objects and compare their densities.", "Investigation"),
        ("Unit conversion challenge", "Convert measurements before calculating area, volume or density.", "Problem Solving"),
    ],
    "PHY-LO4": [
        ("Error spotting", "Examine measurement scenarios and identify parallax, wrong instrument, poor recording or random error.", "Case Study"),
        ("Repeat and average", "Take repeated measurements, calculate an average and explain why the result is more reliable.", "Practical"),
        ("Reliability improvement plan", "Improve a weak measurement procedure by choosing better tools and controls.", "Critical Thinking"),
    ],
    "PHY-LO5": [
        ("Fair-test planner", "Plan an investigation by identifying the variable to change, measure and control.", "Project"),
        ("Measurement data table", "Collect measurements and arrange them in a clear table with headings and units.", "Practical"),
        ("Graph and trend report", "Draw a graph from measurements and write a conclusion supported by the trend.", "Presentation"),
    ],
}
for outcome_code, rows in activities.items():
    outcome_id = get_id("SELECT outcome_id FROM learning_outcomes WHERE outcome_code=?", (outcome_code,))
    for title, desc, typ in rows:
        cur.execute("""
            INSERT INTO learning_activities (outcome_id, activity_title, activity_description, activity_type)
            SELECT ?, ?, ?, ?
            WHERE NOT EXISTS (SELECT 1 FROM learning_activities WHERE outcome_id=? AND activity_title=?)
        """, (outcome_id, title, desc, typ, outcome_id, title))

# Adaptive notes and videos by concept tag
notes = {
    "ICT-LO1": [
        ("ict_meaning", "What ICT Means", "ICT combines information handling and communication using technology. Think of ICT as tools and methods used to collect, process, store, and share information."),
        ("data_information", "Data vs Information", "Data are raw facts such as 12, Elijah, or 35°C. Information is data that has been processed and given meaning, such as 'Elijah scored 12 out of 15'."),
        ("processing_cycle", "Information Processing Cycle", "The cycle moves from input to processing, storage, output, and communication. A keyboard enters data, the CPU processes it, storage keeps it, and a screen or printer outputs it."),
    ],
    "ICT-LO2": [
        ("ict_tools", "Common ICT Tools", "Computers, printers, cameras, projectors, scanners, phones, routers, and storage devices are ICT tools used to create, process, store, and communicate information."),
        ("ict_uses", "Applications of ICT", "ICT is used in education for learning platforms, in health for patient records, in banking for ATMs and mobile money, and in agriculture for weather and market information."),
        ("ict_safety", "ICT Safety", "Avoid liquids near computers, use good posture, keep passwords private, report faulty cables, and take breaks to reduce eye strain."),
    ],
    "PHY-LO1": [
        ("physical_quantities", "Physical Quantities", "A physical quantity is something that can be measured, such as length, mass, time, temperature, area, volume, or density."),
        ("si_units", "SI Units", "SI units are standard units used in science. Examples include metre (m), kilogram (kg), second (s), ampere (A), and kelvin (K)."),
        ("unit_symbols", "Writing Units Correctly", "Use the correct unit symbol and do not pluralize symbols. Write 5 m, not 5 metres when using symbols; write 10 kg, not 10 kgs."),
    ],
    "PHY-LO2": [
        ("instruments", "Choosing Measuring Instruments", "Use a metre rule for length, stopwatch for time, thermometer for temperature, measuring cylinder for liquid volume, and beam balance for mass."),
        ("scale_reading", "Reading Scales", "Read a scale at eye level to avoid parallax error. Identify the smallest division before recording the measurement."),
        ("accuracy", "Accuracy and Recording", "Accurate measurements use suitable instruments, correct units, repeated readings, and careful recording to the appropriate precision."),
    ],
    "ICT-LO3": [
        ("ict_tool_use", "Using ICT Tools to Produce Evidence", "Competent ICT use means selecting a suitable tool, using it safely, producing useful evidence and saving or presenting the result clearly."),
        ("maintenance", "Handling and Maintaining ICT Tools", "Learners protect ICT tools by carrying them carefully, keeping them dry and dust-free, saving work, shutting down correctly and reporting faults."),
        ("processing_cycle", "Producing a Complete ICT Output", "A complete ICT product moves through input, processing, storage, output and communication. The learner should explain each stage in the work produced."),
    ],
    "ICT-LO4": [
        ("ict_safety", "Applying ICT Safety Rules", "Safe ICT practice includes correct posture, avoiding liquids near devices, managing cables, reporting faults and following laboratory procedures."),
        ("maintenance", "Responsible Device Care", "Responsible users protect shared equipment, avoid rough handling, keep devices clean, use stable power and leave the workspace ready for the next learner."),
        ("ict_tool_use", "Responsible Digital Behaviour", "Responsible ICT use includes protecting passwords, respecting other people's files and using information ethically."),
    ],
    "PHY-LO3": [
        ("area_volume", "Measuring Area and Volume", "Area and volume are derived quantities. Learners measure length dimensions carefully, use the correct formula and record the answer with correct units."),
        ("density", "Calculating Density", "Density links mass and volume. Learners measure mass and volume, divide mass by volume and use the result to compare materials."),
        ("unit_symbols", "Converting Before Calculation", "Measurements should use compatible units before calculation. Convert centimetres to metres or grams to kilograms where the task requires it."),
    ],
    "PHY-LO4": [
        ("error_sources", "Identifying Measurement Errors", "Errors may come from parallax, unsuitable instruments, poor zeroing, careless reading, random variation or missing units."),
        ("accuracy", "Repeating and Averaging Readings", "Repeated readings help learners notice unusual values and calculate an average that better represents the measured quantity."),
        ("scale_reading", "Improving Reading Reliability", "Learners improve reliability by reading scales at eye level, using the correct instrument and recording the smallest sensible division."),
    ],
    "PHY-LO5": [
        ("fair_test", "Planning a Fair Test", "A fair test changes one variable, measures one response and keeps other conditions constant so the evidence is trustworthy."),
        ("graphs_trends", "Using Graphs to Communicate Evidence", "Tables and graphs help learners organise measurements, identify patterns and explain trends from practical work."),
        ("scientific_notation", "Recording Very Large or Small Values", "Scientific notation and significant figures help learners record measurements clearly when values are very large, very small or require suitable precision."),
    ],
}
videos = {
    "ict_meaning": ("What is ICT?", "https://www.youtube.com/results?search_query=what+is+ICT+for+students", "Introductory video search on ICT meaning."),
    "data_information": ("Data and Information", "https://www.youtube.com/results?search_query=data+versus+information+ICT", "Video support for data and information."),
    "processing_cycle": ("Information Processing Cycle", "https://www.youtube.com/results?search_query=information+processing+cycle+ICT", "Video support for input, process, storage, output."),
    "ict_tools": ("ICT Tools", "https://www.youtube.com/results?search_query=common+ICT+tools+for+students", "Video support for identifying ICT tools."),
    "ict_uses": ("Uses of ICT", "https://www.youtube.com/results?search_query=uses+of+ICT+in+society", "Video support for ICT applications."),
    "ict_safety": ("Computer Lab Safety", "https://www.youtube.com/results?search_query=computer+lab+safety+rules+for+students", "Video support for safety."),
    "physical_quantities": ("Physical Quantities", "https://www.youtube.com/results?search_query=physical+quantities+and+units+physics", "Video support for physical quantities."),
    "si_units": ("SI Units", "https://www.youtube.com/results?search_query=SI+units+physics+for+students", "Video support for SI units."),
    "unit_symbols": ("Unit Symbols", "https://www.youtube.com/results?search_query=physics+unit+symbols+SI+units", "Video support for unit symbols."),
    "instruments": ("Measuring Instruments", "https://www.youtube.com/results?search_query=measuring+instruments+in+physics", "Video support for instruments."),
    "scale_reading": ("Reading Measuring Scales", "https://www.youtube.com/results?search_query=how+to+read+measuring+scales+physics", "Video support for reading scales."),
    "accuracy": ("Accuracy in Measurement", "https://www.youtube.com/results?search_query=accuracy+and+precision+in+measurement+physics", "Video support for accuracy."),
    "ict_tool_use": ("Using ICT Tools for School Tasks", "https://www.youtube.com/results?search_query=using+ICT+tools+for+students", "Video support for selecting and using ICT tools."),
    "maintenance": ("Computer Care and Maintenance", "https://www.youtube.com/results?search_query=computer+care+and+maintenance+for+students", "Video support for handling and maintaining ICT tools."),
    "area_volume": ("Area and Volume Measurement", "https://www.youtube.com/results?search_query=area+volume+measurement+physics+students", "Video support for area and volume."),
    "density": ("Density in Physics", "https://www.youtube.com/results?search_query=density+mass+volume+physics+students", "Video support for density."),
    "error_sources": ("Sources of Error in Measurement", "https://www.youtube.com/results?search_query=sources+of+error+in+measurement+physics", "Video support for measurement errors."),
    "fair_test": ("Planning a Fair Test", "https://www.youtube.com/results?search_query=planning+a+fair+test+science+students", "Video support for fair-test investigations."),
    "graphs_trends": ("Drawing Graphs in Science", "https://www.youtube.com/results?search_query=drawing+graphs+in+science+experiments", "Video support for tables, graphs and trends."),
    "scientific_notation": ("Scientific Notation in Physics", "https://www.youtube.com/results?search_query=scientific+notation+physics+students", "Video support for scientific notation."),
}
for outcome_code, rows in notes.items():
    outcome_id = get_id("SELECT outcome_id FROM learning_outcomes WHERE outcome_code=?", (outcome_code,))
    for concept, title, body in rows:
        cur.execute("""
            INSERT INTO concepts
            (outcome_id, concept_tag, concept_title, concept_description, generic_skill, cross_cutting_issue, curriculum_value)
            SELECT ?, ?, ?, ?, 'Critical thinking and communication', 'Responsible use of technology and resources', 'Accuracy, safety and collaboration'
            WHERE NOT EXISTS (SELECT 1 FROM concepts WHERE outcome_id=? AND concept_tag=?)
        """, (outcome_id, concept, title, body, outcome_id, concept))
        cur.execute("""
            INSERT INTO adaptive_notes (outcome_id, concept_tag, note_title, note_body)
            SELECT ?, ?, ?, ?
            WHERE NOT EXISTS (SELECT 1 FROM adaptive_notes WHERE outcome_id=? AND concept_tag=? AND note_title=?)
        """, (outcome_id, concept, title, body, outcome_id, concept, title))
        cur.execute("""
            INSERT INTO learning_resources
            (outcome_id, concept_tag, resource_type, resource_title, resource_body, estimated_minutes)
            SELECT ?, ?, 'note', ?, ?, 10
            WHERE NOT EXISTS (
                SELECT 1 FROM learning_resources
                WHERE outcome_id=? AND concept_tag=? AND resource_type='note' AND resource_title=?
            )
        """, (outcome_id, concept, title, body, outcome_id, concept, title))
        vtitle, vurl, vdesc = videos[concept]
        cur.execute("""
            INSERT INTO adaptive_videos (outcome_id, concept_tag, video_title, video_url, video_description)
            SELECT ?, ?, ?, ?, ?
            WHERE NOT EXISTS (SELECT 1 FROM adaptive_videos WHERE outcome_id=? AND concept_tag=? AND video_title=?)
        """, (outcome_id, concept, vtitle, vurl, vdesc, outcome_id, concept, vtitle))
        cur.execute("""
            INSERT INTO learning_resources
            (outcome_id, concept_tag, resource_type, resource_title, resource_body, resource_url, estimated_minutes)
            SELECT ?, ?, 'video', ?, ?, ?, 8
            WHERE NOT EXISTS (
                SELECT 1 FROM learning_resources
                WHERE outcome_id=? AND concept_tag=? AND resource_type='video' AND resource_title=?
            )
        """, (outcome_id, concept, vtitle, vdesc, vurl, outcome_id, concept, vtitle))

# Assessment data. Each LO has pretest, practice, and posttest.
assessments = {
    "ICT-LO1": {
        "pretest": [
            ("What does ICT stand for?", "ict_meaning", [("Information and Communication Technology", 1), ("Internet Computer Training", 0), ("Internal Control Technology", 0)]),
            ("Which statement best describes data?", "data_information", [("Raw facts before processing", 1), ("Only printed reports", 0), ("A computer monitor", 0)]),
            ("Which stage comes after input in the information processing cycle?", "processing_cycle", [("Processing", 1), ("Sweeping", 0), ("Painting", 0)]),
        ],
        "practice": [
            ("A learner types marks into a spreadsheet. This is mainly which stage?", "processing_cycle", [("Input", 1), ("Output", 0), ("Communication", 0)]),
            ("The final class average displayed after calculations is best called?", "data_information", [("Information", 1), ("Raw data", 0), ("Hardware", 0)]),
            ("ICT helps people mainly by", "ict_meaning", [("processing and communicating information", 1), ("removing all teachers", 0), ("making books unnecessary", 0)]),
        ],
        "posttest": [
            ("Which example shows ICT communication?", "ict_meaning", [("Sending an email", 1), ("Lifting a chair", 0), ("Sharpening a pencil", 0)]),
            ("Processed data that has meaning is called", "data_information", [("Information", 1), ("Noise", 0), ("Keyboard", 0)]),
            ("A printer mainly performs which stage?", "processing_cycle", [("Output", 1), ("Input", 0), ("Processing", 0)]),
        ],
    },
    "ICT-LO2": {
        "pretest": [
            ("Which of these is an ICT tool?", "ict_tools", [("Projector", 1), ("Broom", 0), ("Chalk duster", 0)]),
            ("Which field uses ICT for patient records?", "ict_uses", [("Health", 1), ("Only football", 0), ("Only sweeping", 0)]),
            ("Why should learners avoid drinks near computers?", "ict_safety", [("To prevent damage and electrical risks", 1), ("To increase screen brightness", 0), ("To make typing faster", 0)]),
        ],
        "practice": [
            ("Which device captures photos and videos?", "ict_tools", [("Camera", 1), ("Stapler", 0), ("Basin", 0)]),
            ("Mobile money is an example of ICT use in", "ict_uses", [("Banking and finance", 1), ("Only gardening", 0), ("Only football", 0)]),
            ("A safe password should be", "ict_safety", [("kept private", 1), ("shared with everyone", 0), ("written on the monitor", 0)]),
        ],
        "posttest": [
            ("Which device displays information to many learners?", "ict_tools", [("Projector", 1), ("Hoe", 0), ("Cup", 0)]),
            ("ICT can support agriculture by providing", "ict_uses", [("weather and market information", 1), ("only chalk", 0), ("only chairs", 0)]),
            ("Good posture when using computers helps to", "ict_safety", [("reduce body strain", 1), ("destroy the chair", 0), ("hide information", 0)]),
        ],
    },
    "ICT-LO3": {
        "pretest": [
            ("Before using an ICT tool, a learner should first consider", "ict_tool_use", [("the task and suitable tool", 1), ("the colour of the chair", 0), ("how to avoid saving work", 0)]),
            ("Which action helps maintain ICT tools?", "maintenance", [("Shutting down correctly", 1), ("Pulling cables roughly", 0), ("Eating over the keyboard", 0)]),
            ("Saving a completed report is part of which ICT stage?", "processing_cycle", [("Storage", 1), ("Parallax", 0), ("Mass measurement", 0)]),
        ],
        "practice": [
            ("A learner needs evidence of a practical activity. Which tool can capture it?", "ict_tool_use", [("Camera or phone camera", 1), ("Thermometer", 0), ("Beam balance", 0)]),
            ("A good maintenance habit after finishing computer work is to", "maintenance", [("save work and shut down properly", 1), ("leave files unsaved", 0), ("disconnect everything by pulling", 0)]),
            ("Typing, editing and saving a notice shows", "processing_cycle", [("input, processing and storage", 1), ("density only", 0), ("fair test only", 0)]),
        ],
        "posttest": [
            ("Competent ICT use is best shown when a learner", "ict_tool_use", [("selects a tool and produces useful evidence", 1), ("names a tool without using it", 0), ("ignores the task", 0)]),
            ("Reporting a faulty keyboard before use shows", "maintenance", [("responsible maintenance", 1), ("unsafe practice", 0), ("unit conversion", 0)]),
            ("Presenting saved work to the class mainly involves", "processing_cycle", [("output and communication", 1), ("mass and density", 0), ("parallax error", 0)]),
        ],
    },
    "ICT-LO4": {
        "pretest": [
            ("Which is a safe ICT laboratory practice?", "ict_safety", [("Keep liquids away from devices", 1), ("Share passwords", 0), ("Touch loose wires", 0)]),
            ("A responsible user protects shared equipment by", "maintenance", [("handling devices carefully", 1), ("dropping devices", 0), ("blocking ventilation", 0)]),
            ("Respecting another learner's files means", "ict_tool_use", [("not opening or changing them without permission", 1), ("deleting them for fun", 0), ("sharing their password", 0)]),
        ],
        "practice": [
            ("If a cable is damaged, the learner should", "ict_safety", [("report it to the teacher", 1), ("continue using it", 0), ("hide it", 0)]),
            ("Cleaning dust from equipment carefully supports", "maintenance", [("longer tool life", 1), ("data loss", 0), ("parallax reduction", 0)]),
            ("A strong password should be", "ict_tool_use", [("kept private", 1), ("written for everyone", 0), ("shared with classmates", 0)]),
        ],
        "posttest": [
            ("Healthy ICT use includes", "ict_safety", [("good posture and short breaks", 1), ("staring without rest", 0), ("bending over the screen", 0)]),
            ("Leaving the ICT workspace ready for the next learner shows", "maintenance", [("responsibility", 1), ("carelessness", 0), ("measurement error", 0)]),
            ("Ethical ICT use includes", "ict_tool_use", [("respecting data and privacy", 1), ("copying files without permission", 0), ("sharing private information", 0)]),
        ],
    },
    "PHY-LO1": {
        "pretest": [
            ("What is a physical quantity?", "physical_quantities", [("Something that can be measured", 1), ("A story only", 0), ("A colour only", 0)]),
            ("What is the SI unit of length?", "si_units", [("metre", 1), ("kilogram", 0), ("second", 0)]),
            ("Which is the correct symbol for metre?", "unit_symbols", [("m", 1), ("kg", 0), ("s", 0)]),
        ],
        "practice": [
            ("Mass is an example of", "physical_quantities", [("physical quantity", 1), ("software", 0), ("a network", 0)]),
            ("The SI unit of time is", "si_units", [("second", 1), ("metre", 0), ("kilogram", 0)]),
            ("The correct symbol for kilogram is", "unit_symbols", [("kg", 1), ("kgs", 0), ("km", 0)]),
        ],
        "posttest": [
            ("Length, mass and time are examples of", "physical_quantities", [("physical quantities", 1), ("computer programs", 0), ("laboratory rules", 0)]),
            ("Which unit is used for mass?", "si_units", [("kilogram", 1), ("second", 0), ("metre", 0)]),
            ("Which expression is written correctly?", "unit_symbols", [("5 m", 1), ("5 ms for length", 0), ("5 kgs", 0)]),
        ],
    },
    "PHY-LO2": {
        "pretest": [
            ("Which instrument measures temperature?", "instruments", [("Thermometer", 1), ("Beam balance", 0), ("Measuring cylinder", 0)]),
            ("Why should the eye be level with the scale?", "scale_reading", [("To avoid parallax error", 1), ("To decorate the instrument", 0), ("To increase mass", 0)]),
            ("Why are repeated readings useful?", "accuracy", [("They improve reliability", 1), ("They remove units", 0), ("They make instruments heavier", 0)]),
        ],
        "practice": [
            ("Which instrument measures liquid volume?", "instruments", [("Measuring cylinder", 1), ("Stopwatch", 0), ("Metre rule", 0)]),
            ("Before reading a scale, first identify", "scale_reading", [("the smallest division", 1), ("the colour of the table", 0), ("the brand name only", 0)]),
            ("A suitable instrument helps improve", "accuracy", [("accuracy", 1), ("carelessness", 0), ("noise", 0)]),
        ],
        "posttest": [
            ("Which instrument measures mass?", "instruments", [("Beam balance", 1), ("Thermometer", 0), ("Stopwatch", 0)]),
            ("Parallax error is reduced by", "scale_reading", [("reading at eye level", 1), ("closing both eyes", 0), ("changing units randomly", 0)]),
            ("Accurate recording should include", "accuracy", [("value and correct unit", 1), ("only a number", 0), ("only a drawing", 0)]),
        ],
    },
    "PHY-LO3": {
        "pretest": [
            ("Area is commonly calculated by", "area_volume", [("length times width", 1), ("mass divided by volume", 0), ("time divided by length", 0)]),
            ("Density is calculated using", "density", [("mass divided by volume", 1), ("length plus width", 0), ("time times temperature", 0)]),
            ("Before calculating, measurements should use", "unit_symbols", [("compatible units", 1), ("random units", 0), ("no units", 0)]),
        ],
        "practice": [
            ("A classroom floor measurement can help estimate", "area_volume", [("area for covering", 1), ("password strength", 0), ("camera quality", 0)]),
            ("An object with high mass in small volume has", "density", [("high density", 1), ("no density", 0), ("only time", 0)]),
            ("200 cm is equal to", "unit_symbols", [("2 m", 1), ("20 m", 0), ("0.2 m", 0)]),
        ],
        "posttest": [
            ("The volume of a rectangular box uses", "area_volume", [("length, width and height", 1), ("mass only", 0), ("time only", 0)]),
            ("To compare the density of two materials, measure", "density", [("mass and volume", 1), ("temperature only", 0), ("colour only", 0)]),
            ("A correct density unit can be", "unit_symbols", [("g/cm3", 1), ("seconds", 0), ("metres only", 0)]),
        ],
    },
    "PHY-LO4": {
        "pretest": [
            ("Parallax is an example of", "error_sources", [("measurement error", 1), ("data privacy", 0), ("ICT output", 0)]),
            ("Repeating measurements helps to", "accuracy", [("improve reliability", 1), ("remove all instruments", 0), ("avoid units", 0)]),
            ("A scale should be read", "scale_reading", [("at eye level", 1), ("from any angle", 0), ("without looking", 0)]),
        ],
        "practice": [
            ("Using a ruler for a very tiny wire may cause error because", "error_sources", [("the instrument is unsuitable", 1), ("the wire is data", 0), ("the unit is private", 0)]),
            ("The average of 4 s, 5 s and 6 s is", "accuracy", [("5 s", 1), ("15 s", 0), ("1 s", 0)]),
            ("Identifying the smallest division helps improve", "scale_reading", [("precision of reading", 1), ("password safety", 0), ("file storage", 0)]),
        ],
        "posttest": [
            ("A learner reduces error by", "error_sources", [("using a suitable instrument and reading correctly", 1), ("guessing values", 0), ("omitting units", 0)]),
            ("If repeated readings are close, the result is likely more", "accuracy", [("reliable", 1), ("secret", 0), ("unrelated", 0)]),
            ("Parallax is reduced when the eye is", "scale_reading", [("level with the mark", 1), ("above the roof", 0), ("closed", 0)]),
        ],
    },
    "PHY-LO5": {
        "pretest": [
            ("A fair test changes", "fair_test", [("one variable at a time", 1), ("all variables at once", 0), ("no observations", 0)]),
            ("Graphs help learners identify", "graphs_trends", [("patterns and trends", 1), ("passwords", 0), ("keyboard keys", 0)]),
            ("Scientific notation is useful for", "scientific_notation", [("very large or small values", 1), ("hiding results", 0), ("removing units", 0)]),
        ],
        "practice": [
            ("In a fair test, variables kept the same are called", "fair_test", [("controlled variables", 1), ("deleted values", 0), ("private files", 0)]),
            ("A table of readings should include", "graphs_trends", [("headings and units", 1), ("only drawings", 0), ("no labels", 0)]),
            ("4500 can be written as", "scientific_notation", [("4.5 x 10^3", 1), ("45 x 10^0 only", 0), ("0.45 x 10^-3", 0)]),
        ],
        "posttest": [
            ("A good investigation conclusion should be based on", "fair_test", [("evidence collected", 1), ("guessing", 0), ("someone's password", 0)]),
            ("A rising line on a graph may show", "graphs_trends", [("an increasing trend", 1), ("no relationship always", 0), ("a broken ruler", 0)]),
            ("0.003 can be written as", "scientific_notation", [("3 x 10^-3", 1), ("3 x 10^3", 0), ("30 x 10^3", 0)]),
        ],
    },
}

for outcome_code, by_type in assessments.items():
    outcome_id = get_id("SELECT outcome_id FROM learning_outcomes WHERE outcome_code=?", (outcome_code,))
    lesson_id = get_id("SELECT lesson_id FROM lessons WHERE outcome_id=?", (outcome_id,))
    for assessment_type, qs in by_type.items():
        title = f"{outcome_code} {assessment_type.title()}"
        cur.execute("""
            INSERT INTO assessments (lesson_id, assessment_title, assessment_type, total_marks)
            SELECT ?, ?, ?, ?
            WHERE NOT EXISTS (SELECT 1 FROM assessments WHERE lesson_id=? AND assessment_type=?)
        """, (lesson_id, title, assessment_type, len(qs), lesson_id, assessment_type))
        assessment_id = get_id("SELECT assessment_id FROM assessments WHERE lesson_id=? AND assessment_type=?", (lesson_id, assessment_type))
        for question_text, concept, options in qs:
            cur.execute("""
                INSERT INTO questions
                (assessment_id, question_text, concept_tag, marks, bloom_level, explanation, feedback, resource_hint, estimated_time_minutes)
                SELECT ?, ?, ?, 1, 'Understanding', ?, ?, ?, 2
                WHERE NOT EXISTS (SELECT 1 FROM questions WHERE assessment_id=? AND question_text=?)
            """, (
                assessment_id,
                question_text,
                concept,
                f"This item checks the learner's understanding of {concept.replace('_', ' ')}.",
                "Review the adaptive note, worked example and practice activity for this concept.",
                concept,
                assessment_id,
                question_text,
            ))
            qid = get_id("SELECT question_id FROM questions WHERE assessment_id=? AND question_text=?", (assessment_id, question_text))
            for option_text, is_correct in options:
                cur.execute("""
                    INSERT INTO question_options (question_id, option_text, is_correct)
                    SELECT ?, ?, ?
                    WHERE NOT EXISTS (SELECT 1 FROM question_options WHERE question_id=? AND option_text=?)
                """, (qid, option_text, is_correct, qid, option_text))



# Extra adaptive practice question bank.
# These questions allow Learn2Master to immediately switch to the concept a learner has not mastered.
extra_practice_questions = {
    "ICT-LO1": {
        "ict_meaning": [
            ("Which activity is an example of ICT use?", [("Sending a typed report by email", 1), ("Carrying a desk", 0), ("Sweeping a compound", 0)]),
            ("ICT mainly deals with", [("information and communication using technology", 1), ("only physical exercise", 0), ("only chalk writing", 0)]),
        ],
        "data_information": [
            ("A list of unprocessed temperature readings is", [("data", 1), ("a monitor", 0), ("a printer", 0)]),
            ("A report showing the hottest day from readings is", [("information", 1), ("raw data", 0), ("hardware", 0)]),
        ],
        "processing_cycle": [
            ("Saving a document on a flash disk is mainly", [("storage", 1), ("input", 0), ("sweeping", 0)]),
            ("A monitor showing results represents", [("output", 1), ("storage only", 0), ("raw facts only", 0)]),
        ],
    },
    "ICT-LO2": {
        "ict_tools": [
            ("Which ICT tool scans paper documents into digital form?", [("Scanner", 1), ("Cup", 0), ("Desk", 0)]),
            ("Which device stores digital files?", [("Flash disk", 1), ("Broom", 0), ("Chalk", 0)]),
        ],
        "ict_uses": [
            ("ICT in education can support", [("online learning and research", 1), ("only carrying water", 0), ("only sweeping", 0)]),
            ("ICT in transport can support", [("ticket booking and tracking", 1), ("cooking food only", 0), ("washing clothes only", 0)]),
        ],
        "ict_safety": [
            ("Reporting a damaged cable is important because it", [("reduces electrical risk", 1), ("makes typing slower", 0), ("increases dust", 0)]),
            ("Taking breaks when using computers helps reduce", [("eye strain and fatigue", 1), ("storage space", 0), ("keyboard letters", 0)]),
        ],
    },
    "PHY-LO1": {
        "physical_quantities": [
            ("Which of these can be measured?", [("Time", 1), ("Happiness only", 0), ("Beauty only", 0)]),
            ("Volume is a physical quantity because it", [("can be measured", 1), ("is only a story", 0), ("has no unit", 0)]),
        ],
        "si_units": [
            ("Which is the SI unit of mass?", [("kilogram", 1), ("metre", 0), ("second", 0)]),
            ("Which is the SI unit of time?", [("second", 1), ("kilogram", 0), ("metre", 0)]),
        ],
        "unit_symbols": [
            ("Which is the correct symbol for second?", [("s", 1), ("sec(s)", 0), ("kg", 0)]),
            ("Which unit symbol is correctly written?", [("10 kg", 1), ("10 kgs", 0), ("10 Kilogrammes", 0)]),
        ],
    },
    "PHY-LO2": {
        "instruments": [
            ("Which instrument measures time in an experiment?", [("Stopwatch", 1), ("Thermometer", 0), ("Measuring cylinder", 0)]),
            ("Which instrument measures length?", [("Metre rule", 1), ("Beam balance", 0), ("Clock only", 0)]),
        ],
        "scale_reading": [
            ("The smallest division on a scale helps determine", [("precision of reading", 1), ("colour of the instrument", 0), ("mass of the learner", 0)]),
            ("Parallax error occurs when", [("the eye is not level with the scale", 1), ("the unit is written", 0), ("readings are repeated", 0)]),
        ],
        "accuracy": [
            ("Repeating readings helps to", [("improve reliability", 1), ("remove all units", 0), ("make values random", 0)]),
            ("A good measurement record should include", [("value and unit", 1), ("only the learner name", 0), ("only the date", 0)]),
        ],
    },
}

for outcome_code, concept_groups in extra_practice_questions.items():
    outcome_id = get_id("SELECT outcome_id FROM learning_outcomes WHERE outcome_code=?", (outcome_code,))
    lesson_id = get_id("SELECT lesson_id FROM lessons WHERE outcome_id=?", (outcome_id,))
    assessment_id = get_id("SELECT assessment_id FROM assessments WHERE lesson_id=? AND assessment_type='practice'", (lesson_id,))
    for concept, rows in concept_groups.items():
        for question_text, options in rows:
            cur.execute("""
                INSERT INTO questions
                (assessment_id, question_text, concept_tag, marks, bloom_level, explanation, feedback, resource_hint, estimated_time_minutes)
                SELECT ?, ?, ?, 1, 'Application', ?, ?, ?, 2
                WHERE NOT EXISTS (SELECT 1 FROM questions WHERE assessment_id=? AND question_text=?)
            """, (
                assessment_id,
                question_text,
                concept,
                f"This adaptive practice item targets {concept.replace('_', ' ')}.",
                "Use the feedback to revisit weak concepts before the post-test unlocks.",
                concept,
                assessment_id,
                question_text,
            ))
            qid = get_id("SELECT question_id FROM questions WHERE assessment_id=? AND question_text=?", (assessment_id, question_text))
            for option_text, is_correct in options:
                cur.execute("""
                    INSERT INTO question_options (question_id, option_text, is_correct)
                    SELECT ?, ?, ?
                    WHERE NOT EXISTS (SELECT 1 FROM question_options WHERE question_id=? AND option_text=?)
                """, (qid, option_text, is_correct, qid, option_text))



# V8 worked examples: bridge between adaptive notes and practice.
worked_examples = {
    "ICT-LO1": [
        ("ict_meaning", "ICT in a school office", "A bursar enters fees payments into a computer and sends receipts by email.", "Step 1: Identify the information task. Step 2: Identify the technology used. Step 3: Explain that computers and email support information processing and communication."),
        ("data_information", "From raw marks to class average", "Marks 45, 60 and 75 are data. After calculating an average of 60, the result becomes information.", "Data are raw facts. Processing gives meaning. The average helps a teacher make a decision."),
        ("processing_cycle", "Typing and printing a report", "A learner types text using a keyboard, the computer processes it, saves it, then prints it.", "Keyboard=input, CPU=processing, disk=storage, printer=output."),
    ],
    "ICT-LO2": [
        ("ict_tools", "Choosing tools for a presentation", "A projector, laptop and flash disk can be used to present group work.", "Choose tool according to task: laptop prepares, flash disk stores, projector displays."),
        ("ict_uses", "ICT in health", "A hospital uses computers to store patient records and send appointment messages.", "Identify sector, information handled, and benefit."),
        ("ict_safety", "Preventing lab accidents", "A learner finds a loose cable and reports it instead of touching it.", "Recognize risk, avoid contact, report to teacher/lab attendant."),
    ],
    "PHY-LO1": [
        ("physical_quantities", "Identifying measurable properties", "A desk has length, mass and volume. These are measurable, so they are physical quantities.", "Ask: Can it be measured? If yes, identify suitable unit."),
        ("si_units", "Selecting SI units", "A learner records length in metres and time in seconds during an experiment.", "Identify quantity first, then select the correct SI unit."),
        ("unit_symbols", "Writing units correctly", "The correct way to record a length is 5 m, not 5 metres when using symbols.", "Use standard symbols and avoid pluralizing symbols."),
    ],
    "PHY-LO2": [
        ("instruments", "Selecting the best instrument", "To measure liquid volume, use a measuring cylinder, not a metre rule.", "Identify what is being measured, then select the instrument designed for that quantity."),
        ("scale_reading", "Avoiding parallax error", "When reading a measuring cylinder, place the eye level with the meniscus.", "Eye level reduces parallax and improves reading accuracy."),
        ("accuracy", "Improving reliability", "Repeating a time measurement three times and averaging can reduce random error.", "Repeat readings, compare values, and record final value with correct unit."),
    ],
    "ICT-LO3": [
        ("ict_tool_use", "Producing evidence with a phone camera", "A learner photographs a labelled ICT tool, saves the image and writes a caption explaining its use.", "Choose the tool, capture evidence, save the file, add meaning and present it."),
        ("maintenance", "Maintaining a shared computer", "After using a shared computer, a learner saves work, closes programs, shuts down correctly and leaves the workspace clean.", "Protect work first, shut down through the system, then check the workspace."),
        ("processing_cycle", "Creating a class announcement", "A learner types an announcement, edits it, saves it, prints it and shares it with classmates.", "Map the task to input, processing, storage, output and communication."),
    ],
    "ICT-LO4": [
        ("ict_safety", "Responding to a loose cable", "A learner notices a loose power cable near a computer and reports it instead of touching or using it.", "Identify danger, avoid contact, inform the teacher and keep others away."),
        ("maintenance", "Preventing device damage", "A learner keeps drinks away, avoids blocking ventilation and carries a laptop with both hands.", "Identify the risk, choose a safe behaviour and explain the benefit."),
        ("ict_tool_use", "Protecting a classmate's file", "A learner finds another learner's file open and closes it without reading or changing it.", "Respect privacy, avoid changing data and report if help is needed."),
    ],
    "PHY-LO3": [
        ("area_volume", "Estimating paint needed for a wall", "A learner measures wall length and height to calculate area before estimating covering material.", "Measure length and height, multiply for area and record square units."),
        ("density", "Comparing two blocks", "Two blocks have different masses and volumes. The learner calculates density to compare how compact each material is.", "Measure mass, measure volume, divide mass by volume and compare results."),
        ("unit_symbols", "Converting before density calculation", "A learner converts centimetres to metres or grams to kilograms when a task requires consistent units.", "Check units, convert where needed, calculate and label the answer."),
    ],
    "PHY-LO4": [
        ("error_sources", "Choosing a better instrument", "A learner uses a tape measure for a long wall instead of a short ruler to reduce error.", "Identify the source of error and select a more suitable instrument."),
        ("accuracy", "Average of repeated readings", "A learner measures a time three times and calculates the average to make the final value more reliable.", "Repeat, add readings, divide by number of readings and record units."),
        ("scale_reading", "Correct reading position", "A learner reads a measuring cylinder at eye level instead of from above.", "Position the eye level with the mark and record the value with correct units."),
    ],
    "PHY-LO5": [
        ("fair_test", "Testing stretch of a rubber band", "A learner changes the load on a rubber band, measures extension and keeps the same rubber band and method.", "Change one variable, measure one response and control the rest."),
        ("graphs_trends", "Graphing extension results", "A learner records load and extension in a table, draws a graph and explains the trend.", "Create table headings, plot points, draw trend and write a conclusion."),
        ("scientific_notation", "Recording small times", "A learner writes 0.003 s as 3 x 10^-3 s to make a very small value clear.", "Move the decimal, count places and write the power of ten with the unit."),
    ],
}

for outcome_code, rows in worked_examples.items():
    outcome_id = get_id("SELECT outcome_id FROM learning_outcomes WHERE outcome_code=?", (outcome_code,))
    for concept, title, body, steps in rows:
        cur.execute("""
            INSERT INTO worked_examples (outcome_id, concept_tag, example_title, example_body, step_by_step_solution)
            SELECT ?, ?, ?, ?, ?
            WHERE NOT EXISTS (SELECT 1 FROM worked_examples WHERE outcome_id=? AND concept_tag=? AND example_title=?)
        """, (outcome_id, concept, title, body, steps, outcome_id, concept, title))
        cur.execute("""
            INSERT INTO learning_resources
            (outcome_id, concept_tag, resource_type, resource_title, resource_body, estimated_minutes)
            SELECT ?, ?, 'worked_example', ?, ?, 12
            WHERE NOT EXISTS (
                SELECT 1 FROM learning_resources
                WHERE outcome_id=? AND concept_tag=? AND resource_type='worked_example' AND resource_title=?
            )
        """, (outcome_id, concept, title, f"{body}\n\n{steps}", outcome_id, concept, title))


# Book-enriched content from the uploaded ICT prototype/syllabus and Physics book/syllabus.
# The wording below is paraphrased for the prototype and kept concept-tagged so the adaptive flow stays stable.
supplemental_notes = {
    "ICT-LO1": [
        ("ict_meaning", "ICT as a System", "ICT can be understood as a system where technology handles information and communication. Devices, people, procedures and networks work together so messages, records, images, sound or calculations can move from one place or form to another."),
        ("ict_meaning", "ICT and Everyday Problem Solving", "ICT is useful because it helps learners solve real problems: preparing reports, communicating with others, finding information, keeping records, presenting ideas and improving work in different subjects."),
        ("data_information", "Examples of Data Becoming Information", "Marks, names, dates and temperatures are data when they are still raw. They become information when arranged, calculated or interpreted, such as a class average, a weather summary or a list of learners who need support."),
        ("processing_cycle", "The ICT Processing Cycle in Practice", "A complete ICT task often starts with input, then processing, storage, output and communication. For example, a learner types data, a computer calculates a result, saves the file, displays the result and sends it to a teacher."),
    ],
    "ICT-LO2": [
        ("ict_tools", "ICT Tool Characteristics", "An ICT tool is usually electronic, works with data or information, and supports one or more tasks such as capture, processing, storage, output or communication. A computer system has both hardware and software, while a radio or phone may focus mainly on communication."),
        ("ict_tools", "ICT Tools in Professional Fields", "Different fields use different ICT tools. Health workers use computers for records, teachers use projectors and learning platforms, farmers may use phones for weather and market information, while offices use printers, scanners and storage devices."),
        ("ict_uses", "ICT for Learning and Work", "ICT supports creativity, communication, collaboration, business, research and problem solving. Learners can use it to make presentations, organise files, search for information, share work and prepare for technology-related careers."),
        ("ict_safety", "Handling and Maintaining ICT Tools", "Good handling includes carrying devices carefully, keeping tools dry and dust-free, using stable power, shutting down correctly, reporting faults, and avoiding rough treatment of cables, screens, keyboards and storage devices."),
        ("ict_safety", "Healthy and Responsible ICT Use", "ICT safety also includes protecting passwords, respecting other people's data, sitting correctly, taking short breaks, avoiding glare, keeping food and drinks away, and following laboratory rules before using equipment."),
    ],
    "PHY-LO1": [
        ("physical_quantities", "Measurable and Non-measurable Properties", "Physics focuses on quantities that can be measured accurately. Length, mass, time, area, volume, density and temperature can be measured, while feelings such as happiness or fear cannot be measured with a standard physics instrument."),
        ("physical_quantities", "Fundamental and Derived Quantities", "Some physical quantities are basic, such as length, mass and time. Other quantities are derived from them; for example, area depends on length times length, volume depends on length cubed, and density depends on mass divided by volume."),
        ("si_units", "Why Standard Units Matter", "Standard units allow scientists and learners to compare results fairly. If each person used a private unit, measurements would be confusing. SI units make records clear across classrooms, laboratories and countries."),
        ("unit_symbols", "Unit Conversion and Scientific Recording", "Good measurement records use correct symbols, spacing and conversions. For example, centimetres can be changed to metres before calculation, and very large or very small values can be written using scientific notation."),
    ],
    "PHY-LO2": [
        ("instruments", "Choosing Instruments by Quantity", "The quantity being measured determines the instrument to use. Length may need a metre rule, tape measure, vernier calliper or micrometer screw gauge depending on size and accuracy required. Mass, volume, time and temperature also require suitable instruments."),
        ("instruments", "Instrument Range and Precision", "An instrument is selected by considering its range and smallest division. A metre rule is suitable for ordinary classroom lengths, a tape measure for longer distances, and a micrometer or vernier calliper for small dimensions needing greater precision."),
        ("scale_reading", "Reducing Reading Errors", "Accurate scale reading requires the eye to be level with the mark, the instrument to be correctly positioned, and the smallest division to be identified before recording. This reduces parallax and careless estimation errors."),
        ("accuracy", "Repeated Readings and Average Values", "Accuracy improves when a learner repeats measurements and calculates an average. Repeated readings help reveal mistakes, reduce random error and make the final result more reliable."),
        ("accuracy", "Fair Tests and Scientific Method", "A practical investigation should be planned as a fair test. The learner identifies what to change, what to measure, what to keep constant, records observations, analyses patterns and justifies conclusions using evidence."),
    ],
}

supplemental_activities = {
    "ICT-LO1": [
        ("ICT system analogy", "Draw a simple ICT system and compare it with another familiar system, identifying the information, technology and communication parts.", "Concept Map"),
        ("Data-to-information challenge", "Collect ten raw facts from the classroom and process them into useful information using a table or summary.", "Interactive Activity"),
        ("Processing-cycle role play", "In groups, act out input, processing, storage, output and communication using a school report scenario.", "Peer Discussion"),
    ],
    "ICT-LO2": [
        ("ICT tools field survey", "Interview learners or staff and record ICT tools used in education, health, agriculture, business and communication.", "Research Task"),
        ("Laboratory safety audit", "Inspect the computer laboratory and prepare a safety checklist with risks, causes and prevention measures.", "Practical"),
        ("Responsible-use debate", "Debate whether learners should use mobile phones for school research, including benefits, risks and safety rules.", "Debate"),
    ],
    "PHY-LO1": [
        ("Quantity sorting table", "Sort classroom examples into physical quantities and non-physical qualities, then identify suitable SI units.", "Sorting"),
        ("Unit conversion relay", "Convert measurements between millimetres, centimetres, metres and kilometres, explaining each step.", "Problem Solving"),
        ("Scientific notation gallery", "Create examples of very large and very small measurements and rewrite them using scientific notation.", "Presentation"),
    ],
    "PHY-LO2": [
        ("Instrument selection station", "Move around stations and choose the best instrument for measuring length, mass, time, volume and temperature.", "Matching"),
        ("Scale-reading practical", "Read different scales at eye level, record values with units, and explain how parallax error was avoided.", "Practical"),
        ("Repeated-measurement investigation", "Measure the same object several times, calculate an average, and discuss why results differ slightly.", "Investigation"),
        ("Fair-test planning", "Plan a short investigation where one variable changes, one is measured, and other conditions are kept constant.", "Project"),
    ],
}

supplemental_examples = {
    "ICT-LO1": [
        ("ict_meaning", "Mobile phone message", "A learner sends a homework reminder by phone. The message is information, the phone is technology, and the network supports communication.", "Identify the message, the device, the communication channel and the purpose of the ICT task."),
        ("data_information", "Attendance data", "A register contains raw names and ticks. When counted and summarised as attendance percentage, it becomes information for decision making.", "Collect data, count totals, calculate the percentage and state what the result means."),
        ("processing_cycle", "Typing a class notice", "A keyboard enters text, the processor handles it, storage saves it, the screen displays it, and a printer or message shares it.", "Map each action to input, processing, storage, output or communication."),
    ],
    "ICT-LO2": [
        ("ict_tools", "Choosing a tool for evidence", "A learner needs to submit a practical report with a photo. A phone camera captures the image, a computer edits the report, and storage keeps the file.", "Choose tools according to capture, editing, storage and submission tasks."),
        ("ict_uses", "ICT in agriculture", "A farmer checks weather information and market prices using a phone before deciding when to sell produce.", "Identify the sector, the information needed, the ICT tool and the decision supported."),
        ("ict_safety", "Safe computer shutdown", "A learner saves work, closes programs, shuts down from the operating system and switches off power safely.", "Protect data first, shut down correctly, then handle power and equipment safely."),
    ],
    "PHY-LO1": [
        ("physical_quantities", "Classroom measurement list", "A desk has measurable length, width and height. The neatness of the desk is an opinion, not a physical quantity.", "Separate measurable properties from opinions and give a unit for each measurable property."),
        ("si_units", "Choosing units for a report", "A learner measures desk length in metres, mass in kilograms and time in seconds so another learner can understand the report.", "Identify the quantity, select the SI unit, then record the value and symbol."),
        ("unit_symbols", "Converting centimetres to metres", "A 250 cm table length is converted to 2.5 m before comparison with another measurement in metres.", "Divide centimetres by 100 and write the answer with the correct unit symbol."),
    ],
    "PHY-LO2": [
        ("instruments", "Small-diameter measurement", "A wire is too thin for an ordinary ruler to measure accurately, so a micrometer screw gauge is more suitable.", "Identify the size of the object, choose a precise instrument, then record with suitable precision."),
        ("scale_reading", "Reading a measuring cylinder", "A learner places the eye level with the liquid mark before recording the volume to avoid parallax error.", "Place the cylinder upright, read at eye level, identify the scale division and record with units."),
        ("accuracy", "Average time for a run", "Three stopwatch readings for the same short run are close but not identical. Averaging them gives a more reliable time.", "Repeat the measurement, add the readings, divide by the number of readings and record the average."),
    ],
}

supplemental_questions = {
    "ICT-LO1": {
        "ict_meaning": [
            ("In an ICT system, which part is the technology in a phone call?", [("The mobile phone and network", 1), ("The greeting only", 0), ("The caller's handwriting", 0)]),
            ("Why is ICT useful in school?", [("It helps process, store and communicate information", 1), ("It replaces all practical work", 0), ("It removes the need for safety rules", 0)]),
        ],
        "data_information": [
            ("Attendance ticks become information when they are", [("counted and interpreted", 1), ("ignored", 0), ("rubbed from the register", 0)]),
            ("Which item is raw data before processing?", [("A list of test marks", 1), ("A class average with conclusion", 0), ("A teacher's decision based on results", 0)]),
        ],
        "processing_cycle": [
            ("Saving a typed report mainly represents", [("storage", 1), ("input only", 0), ("measurement", 0)]),
            ("Sending the finished report by email mainly represents", [("communication", 1), ("parallax", 0), ("unit conversion", 0)]),
        ],
    },
    "ICT-LO2": {
        "ict_tools": [
            ("Which tool is best for capturing an experiment photo?", [("Camera or phone camera", 1), ("Keyboard only", 0), ("Desk", 0)]),
            ("A scanner is mainly used to", [("convert paper documents into digital form", 1), ("measure mass", 0), ("cool a computer", 0)]),
        ],
        "ict_uses": [
            ("A teacher using a projector is an example of ICT in", [("education", 1), ("weather only", 0), ("soil testing only", 0)]),
            ("Checking market prices by phone can support", [("agriculture and business decisions", 1), ("parallax reduction", 0), ("physical quantity conversion", 0)]),
        ],
        "ict_safety": [
            ("Why should learners shut down a computer correctly?", [("To protect files and equipment", 1), ("To increase dust", 0), ("To make passwords public", 0)]),
            ("Which habit supports healthy ICT use?", [("Taking breaks and sitting correctly", 1), ("Eating over the keyboard", 0), ("Pulling cables roughly", 0)]),
        ],
    },
    "PHY-LO1": {
        "physical_quantities": [
            ("Which is a derived quantity?", [("Area", 1), ("Time", 0), ("Mass", 0)]),
            ("Which property cannot be measured accurately with a physics instrument?", [("Happiness", 1), ("Length", 0), ("Mass", 0)]),
        ],
        "si_units": [
            ("Why are SI units important?", [("They make measurements standard and comparable", 1), ("They remove the need for instruments", 0), ("They make all quantities the same", 0)]),
            ("Which pair is correctly matched?", [("Time - second", 1), ("Length - kilogram", 0), ("Mass - metre", 0)]),
        ],
        "unit_symbols": [
            ("250 cm is equal to", [("2.5 m", 1), ("25 m", 0), ("0.25 m", 0)]),
            ("Which record uses a correct symbol format?", [("12 cm", 1), ("12 cms", 0), ("12 centimeter symbol", 0)]),
        ],
    },
    "PHY-LO2": {
        "instruments": [
            ("Which instrument is best for a long classroom wall?", [("Tape measure", 1), ("Micrometer screw gauge", 0), ("Stopwatch", 0)]),
            ("Which instrument is more suitable for the diameter of a thin wire?", [("Micrometer screw gauge", 1), ("Measuring cylinder", 0), ("Thermometer", 0)]),
        ],
        "scale_reading": [
            ("Reading a scale with the eye not level causes", [("parallax error", 1), ("storage error", 0), ("software error", 0)]),
            ("Before recording from a scale, a learner should identify", [("the smallest division", 1), ("the colour of the wall", 0), ("the name of the textbook", 0)]),
        ],
        "accuracy": [
            ("A fair test requires learners to", [("change one factor while keeping others controlled", 1), ("change everything at once", 0), ("avoid recording observations", 0)]),
            ("Averaging repeated measurements helps to", [("make the result more reliable", 1), ("remove all units", 0), ("make readings identical every time", 0)]),
        ],
    },
}

concept_illustrations = {
    "ict_meaning": ("ICT system diagram", "img/concepts/ict_meaning.svg", "Shows how information, technology and communication work together in an ICT task."),
    "data_information": ("Data to information diagram", "img/concepts/data_information.svg", "Shows raw facts being processed into useful information for decision making."),
    "processing_cycle": ("Information processing cycle", "img/concepts/processing_cycle.svg", "Shows input, processing, storage, output and communication as a connected cycle."),
    "ict_tools": ("Common ICT tools", "img/concepts/ict_tools.svg", "Shows examples of ICT tools and the tasks they support."),
    "ict_uses": ("ICT uses in society", "img/concepts/ict_uses.svg", "Shows how ICT supports education, health, agriculture, banking and communication."),
    "ict_safety": ("ICT safety checklist", "img/concepts/ict_safety.svg", "Summarises safe, healthy and responsible use of ICT tools."),
    "physical_quantities": ("Physical quantities diagram", "img/concepts/physical_quantities.svg", "Compares measurable physical quantities with qualities that cannot be measured scientifically."),
    "si_units": ("SI units table", "img/concepts/si_units.svg", "Shows common physical quantities and their standard SI units."),
    "unit_symbols": ("Writing units correctly", "img/concepts/unit_symbols.svg", "Shows correct unit symbols and a centimetre-to-metre conversion example."),
    "instruments": ("Choosing measuring instruments", "img/concepts/instruments.svg", "Shows instruments matched to length, time, mass and volume."),
    "scale_reading": ("Reading scales accurately", "img/concepts/scale_reading.svg", "Shows eye-level reading to reduce parallax error."),
    "accuracy": ("Improving accuracy diagram", "img/concepts/accuracy.svg", "Shows repeated readings, averaging and reliable recording."),
    "ict_tool_use": ("Using ICT tools for a task", "img/concepts/ict_tool_use.svg", "Shows how a learner chooses an ICT tool, uses it safely and produces evidence."),
    "maintenance": ("Handling and maintaining ICT tools", "img/concepts/maintenance.svg", "Shows key steps for caring for ICT tools and reporting faults."),
    "area_volume": ("Area and volume measurement", "img/concepts/area_volume.svg", "Shows area and volume as derived measurements for real spaces and objects."),
    "density": ("Density relationship", "img/concepts/density.svg", "Shows density as mass divided by volume."),
    "error_sources": ("Measurement error sources", "img/concepts/error_sources.svg", "Shows common measurement errors and how to reduce them."),
    "fair_test": ("Fair test planning", "img/concepts/fair_test.svg", "Shows change, measure and control variables in a fair investigation."),
    "graphs_trends": ("Graphs and trends", "img/concepts/graphs_trends.svg", "Shows how measured data can reveal a trend."),
    "scientific_notation": ("Scientific notation", "img/concepts/scientific_notation.svg", "Shows large and small measurements written with powers of ten."),
}

for outcome_code, rows in supplemental_notes.items():
    outcome_id = get_id("SELECT outcome_id FROM learning_outcomes WHERE outcome_code=?", (outcome_code,))
    for concept, title, body in rows:
        cur.execute("""
            INSERT INTO adaptive_notes (outcome_id, concept_tag, note_title, note_body, priority)
            SELECT ?, ?, ?, ?, 2
            WHERE NOT EXISTS (SELECT 1 FROM adaptive_notes WHERE outcome_id=? AND concept_tag=? AND note_title=?)
        """, (outcome_id, concept, title, body, outcome_id, concept, title))
        cur.execute("""
            INSERT INTO learning_resources
            (outcome_id, concept_tag, resource_type, resource_title, resource_body, estimated_minutes)
            SELECT ?, ?, 'note', ?, ?, 12
            WHERE NOT EXISTS (
                SELECT 1 FROM learning_resources
                WHERE outcome_id=? AND concept_tag=? AND resource_type='note' AND resource_title=?
            )
        """, (outcome_id, concept, title, body, outcome_id, concept, title))

for outcome_code, rows in supplemental_activities.items():
    outcome_id = get_id("SELECT outcome_id FROM learning_outcomes WHERE outcome_code=?", (outcome_code,))
    for title, desc, typ in rows:
        cur.execute("""
            INSERT INTO learning_activities (outcome_id, activity_title, activity_description, activity_type)
            SELECT ?, ?, ?, ?
            WHERE NOT EXISTS (SELECT 1 FROM learning_activities WHERE outcome_id=? AND activity_title=?)
        """, (outcome_id, title, desc, typ, outcome_id, title))
        cur.execute("""
            INSERT INTO learning_resources
            (outcome_id, resource_type, resource_title, resource_body, estimated_minutes)
            SELECT ?, 'activity', ?, ?, 20
            WHERE NOT EXISTS (
                SELECT 1 FROM learning_resources
                WHERE outcome_id=? AND resource_type='activity' AND resource_title=?
            )
        """, (outcome_id, title, desc, outcome_id, title))

for outcome_code, rows in supplemental_examples.items():
    outcome_id = get_id("SELECT outcome_id FROM learning_outcomes WHERE outcome_code=?", (outcome_code,))
    for concept, title, body, steps in rows:
        cur.execute("""
            INSERT INTO worked_examples (outcome_id, concept_tag, example_title, example_body, step_by_step_solution)
            SELECT ?, ?, ?, ?, ?
            WHERE NOT EXISTS (SELECT 1 FROM worked_examples WHERE outcome_id=? AND concept_tag=? AND example_title=?)
        """, (outcome_id, concept, title, body, steps, outcome_id, concept, title))
        cur.execute("""
            INSERT INTO learning_resources
            (outcome_id, concept_tag, resource_type, resource_title, resource_body, estimated_minutes)
            SELECT ?, ?, 'worked_example', ?, ?, 12
            WHERE NOT EXISTS (
                SELECT 1 FROM learning_resources
                WHERE outcome_id=? AND concept_tag=? AND resource_type='worked_example' AND resource_title=?
            )
        """, (outcome_id, concept, title, f"{body}\n\n{steps}", outcome_id, concept, title))

for outcome_code, concept_groups in supplemental_questions.items():
    outcome_id = get_id("SELECT outcome_id FROM learning_outcomes WHERE outcome_code=?", (outcome_code,))
    lesson_id = get_id("SELECT lesson_id FROM lessons WHERE outcome_id=?", (outcome_id,))
    assessment_id = get_id("SELECT assessment_id FROM assessments WHERE lesson_id=? AND assessment_type='practice'", (lesson_id,))
    for concept, rows in concept_groups.items():
        for question_text, options in rows:
            cur.execute("""
                INSERT INTO questions
                (assessment_id, question_text, concept_tag, marks, bloom_level, explanation, feedback, resource_hint, estimated_time_minutes)
                SELECT ?, ?, ?, 1, 'Application', ?, ?, ?, 3
                WHERE NOT EXISTS (SELECT 1 FROM questions WHERE assessment_id=? AND question_text=?)
            """, (
                assessment_id,
                question_text,
                concept,
                f"This book-enriched item checks application of {concept.replace('_', ' ')}.",
                "Review the expanded notes, activity and worked example for this concept.",
                concept,
                assessment_id,
                question_text,
            ))
            qid = get_id("SELECT question_id FROM questions WHERE assessment_id=? AND question_text=?", (assessment_id, question_text))
            for option_text, is_correct in options:
                cur.execute("""
                    INSERT INTO question_options (question_id, option_text, is_correct)
                    SELECT ?, ?, ?
                    WHERE NOT EXISTS (SELECT 1 FROM question_options WHERE question_id=? AND option_text=?)
                """, (qid, option_text, is_correct, qid, option_text))

for outcome_code in notes.keys():
    outcome_id = get_id("SELECT outcome_id FROM learning_outcomes WHERE outcome_code=?", (outcome_code,))
    for concept, title, image_path, description in [
        (concept, *concept_illustrations[concept])
        for concept, _, _ in notes[outcome_code]
        if concept in concept_illustrations
    ]:
        cur.execute("""
            INSERT INTO learning_resources
            (outcome_id, concept_tag, resource_type, resource_title, resource_body, resource_url, estimated_minutes)
            SELECT ?, ?, 'concept_map', ?, ?, ?, 5
            WHERE NOT EXISTS (
                SELECT 1 FROM learning_resources
                WHERE outcome_id=? AND concept_tag=? AND resource_type='concept_map' AND resource_title=?
            )
        """, (outcome_id, concept, title, description, image_path, outcome_id, concept, title))

competency_missions = {
    "ICT-LO1": [
        ("project", "Explain an ICT task in your school", "Produce a short poster or audio explanation showing the information, technology and communication parts of a real school task. Evidence: labelled diagram and explanation using your own example. Success criteria: correct ICT parts, clear real-world link and accurate use of terms.", 30),
        ("remediation", "Rebuild the ICT cycle", "Use a familiar task such as sending homework to rebuild input, processing, storage, output and communication. Evidence: completed cycle map.", 15),
        ("enrichment", "Community ICT example", "Find one ICT example from health, agriculture or business and explain the information flow.", 20),
    ],
    "ICT-LO2": [
        ("project", "Choose tools for a community problem", "Select ICT tools for a real task such as recording attendance, announcing an event or keeping shop records. Evidence: tool-choice table with reasons. Success criteria: task fit, correct tool use and clear justification.", 35),
        ("remediation", "Tool matching clinic", "Match tools to capture, process, store, output and communication tasks until each selection is justified.", 15),
        ("enrichment", "Professional field comparison", "Compare ICT tools used in education, health, agriculture and banking.", 25),
    ],
    "ICT-LO3": [
        ("project", "Produce a digital evidence item", "Use an ICT tool to capture or prepare evidence from a classroom task, save it clearly and present it. Evidence: saved file/photo/report and explanation of the processing cycle. Success criteria: correct tool, usable output, safe handling and clear storage.", 40),
        ("remediation", "Safe startup and shutdown drill", "Practise starting, saving, closing programs and shutting down correctly.", 15),
        ("enrichment", "Improve the evidence product", "Add a caption, title, file name and short explanation to make the evidence easier to assess.", 20),
    ],
    "ICT-LO4": [
        ("project", "ICT safety improvement plan", "Inspect an ICT workspace and prepare a safety, health and responsible-use improvement plan. Evidence: checklist, risks and recommended actions. Success criteria: identifies risks, protects people, protects data and protects equipment.", 40),
        ("remediation", "Safety scenario decisions", "Choose safe responses for loose cables, shared passwords, exposed files and poor posture.", 15),
        ("enrichment", "Digital responsibility pledge", "Write a learner-friendly responsible ICT use pledge for the class.", 20),
    ],
    "PHY-LO1": [
        ("investigation", "Classroom measurement audit", "Measure real classroom items, classify each quantity and record values using correct SI units and symbols. Evidence: measurement table. Success criteria: measurable quantities, correct units, correct symbols and clear records.", 35),
        ("remediation", "Quantity and unit sorting", "Sort examples into quantity, unit and symbol until each pair is correct.", 15),
        ("enrichment", "Derived quantity hunt", "Find examples of area, volume and density in the school environment.", 20),
    ],
    "PHY-LO2": [
        ("experiment", "Instrument selection and scale-reading practical", "Measure objects using suitable instruments, read scales correctly and explain why each instrument was chosen. Evidence: readings table and tool justification. Success criteria: suitable instrument, correct scale reading and units.", 40),
        ("remediation", "Scale reading correction", "Practise reading scales at eye level and identifying the smallest division.", 15),
        ("enrichment", "Precision comparison", "Compare readings from a ruler, tape measure and more precise tool where available.", 25),
    ],
    "PHY-LO3": [
        ("investigation", "Measure, calculate and apply area, volume and density", "Solve a real measurement problem such as estimating floor covering, box volume or material density. Evidence: measurements, calculations and decision. Success criteria: correct formula, compatible units, clear working and real use.", 45),
        ("remediation", "Formula builder", "Practise choosing area, volume or density formulas from the quantity being asked.", 15),
        ("enrichment", "Material comparison report", "Compare two materials using density and explain which is more compact.", 25),
    ],
    "PHY-LO4": [
        ("experiment", "Improve a measurement procedure", "Take repeated measurements, identify possible errors, calculate an average and recommend improvements. Evidence: repeated readings table and reliability note. Success criteria: identifies errors, repeats readings, averages correctly and improves the method.", 45),
        ("remediation", "Error detective", "Identify parallax, wrong instrument and missing-unit errors in short scenarios.", 15),
        ("enrichment", "Reliability redesign", "Redesign a poor measurement activity to make the result more reliable.", 25),
    ],
    "PHY-LO5": [
        ("project", "Plan and report a fair-test investigation", "Plan a fair test, collect measurements, draw a graph and write a conclusion from the trend. Evidence: plan, data table, graph and conclusion. Success criteria: one changed variable, controlled conditions, labelled graph and evidence-based conclusion.", 50),
        ("remediation", "Variable sorting", "Sort variables into change, measure and keep constant for different investigations.", 15),
        ("enrichment", "Graph explanation challenge", "Explain what a graph trend means and predict the next likely result.", 25),
    ],
}

for outcome_code, rows in competency_missions.items():
    outcome_id = get_id("SELECT outcome_id FROM learning_outcomes WHERE outcome_code=?", (outcome_code,))
    for resource_type, title, body, minutes in rows:
        cur.execute("""
            INSERT INTO learning_resources
            (outcome_id, resource_type, resource_title, resource_body, estimated_minutes)
            SELECT ?, ?, ?, ?, ?
            WHERE NOT EXISTS (
                SELECT 1 FROM learning_resources
                WHERE outcome_id=? AND resource_type=? AND resource_title=?
            )
        """, (outcome_id, resource_type, title, body, minutes, outcome_id, resource_type, title))

# V8 system settings for CBC/AI governance demonstration.
settings = [
    ("ai_adaptivity_level", "balanced", "How strongly AI adjusts content difficulty from learner evidence.", "AI & Personalization Settings", "select"),
    ("ai_learning_style_profile", "multimodal", "Preferred presentation mode for notes, examples, diagrams and feedback.", "AI & Personalization Settings", "select"),
    ("ai_pacing_mode", "guided_self_paced", "Whether learners move freely or follow AI/teacher pacing toward target dates.", "AI & Personalization Settings", "select"),
    ("ai_tutor_persona", "supportive_coach", "Tone, strictness and hinting style used by AI-generated support.", "AI & Personalization Settings", "select"),
    ("cbc_framework_mapping", "uganda_lower_secondary_cbc", "National or institutional competency framework used for outcome mapping.", "CBC & Mastery Configuration", "select"),
    ("mastery_threshold", "80", "Default score or evidence threshold required to prove mastery.", "CBC & Mastery Configuration", "number"),
    ("practice_threshold", "70", "Minimum concept-practice score before post-test unlock.", "CBC & Mastery Configuration", "number"),
    ("prerequisite_enforcement", "strict", "Whether learners can skip ahead or must unlock outcomes in order.", "CBC & Mastery Configuration", "select"),
    ("strand_visibility", "outcome_concept", "Granularity of the curriculum tree shown to learners and teachers.", "CBC & Mastery Configuration", "select"),
    ("assessment_feedback_mode", "instant_formative_delayed_summative", "When AI explanations and corrective feedback appear.", "Assessment & Evaluation Behaviors", "select"),
    ("proctoring_integrity_mode", "audit_only", "Assessment integrity controls used for high-stakes tasks.", "Assessment & Evaluation Behaviors", "select"),
    ("retry_policy_attempts", "3", "Number of allowed attempts before teacher intervention is recommended.", "Assessment & Evaluation Behaviors", "number"),
    ("retry_cooldown_hours", "0", "Waiting time between mastery assessment attempts.", "Assessment & Evaluation Behaviors", "number"),
    ("alternative_assessment_modes", "teacher_review", "Portfolio, oral, project or practical evidence grading support.", "Assessment & Evaluation Behaviors", "select"),
    ("parent_observer_access", "disabled", "Guardian visibility into learner progress and reports.", "User Roles & Collaboration", "select"),
    ("co_teacher_observer_access", "school_admin_approved", "Controls educator collaboration and live-progress observer access.", "User Roles & Collaboration", "select"),
    ("peer_visibility", "private", "Learner visibility in peer dashboards, groups and leaderboards.", "User Roles & Collaboration", "select"),
    ("student_data_retention_days", "365", "How long learner telemetry and AI evidence records are retained before review.", "Privacy, Safety & Compliance", "number"),
    ("compliance_mode", "local_school_policy", "Privacy-control baseline for consent, export and deletion workflows.", "Privacy, Safety & Compliance", "select"),
    ("content_filtering_level", "strict", "Sensitivity of AI guardrails for learner-generated text and uploads.", "Privacy, Safety & Compliance", "select"),
    ("nudge_frequency", "weekly", "How often AI sends reminders about gaps, deadlines and unfinished practice.", "Notifications & Interventions", "select"),
    ("at_risk_threshold", "60", "Predicted mastery level below which teachers are alerted.", "Notifications & Interventions", "number"),
    ("delivery_channels", "in_app", "Notification channels for learners, teachers and guardians.", "Notifications & Interventions", "select"),
    ("teacher_review_required", "optional", "Teacher review strengthens evidence portfolio but does not block the research demo by default.", "Assessment & Evaluation Behaviors", "select"),
    ("offline_mode", "enabled_foundation", "Offline sync queue and local SQLite storage foundation enabled.", "Privacy, Safety & Compliance", "select"),
    ("bkt_model", "simplified", "Simplified Bayesian Knowledge Tracing used to estimate concept mastery probability.", "AI & Personalization Settings", "select"),
]
for k, v, d, category, setting_type in settings:
    cur.execute("""
        INSERT INTO system_settings
        (setting_key, setting_value, setting_description, setting_category, setting_type)
        SELECT ?, ?, ?, ?, ? WHERE NOT EXISTS (SELECT 1 FROM system_settings WHERE setting_key=?)
    """, (k, v, d, category, setting_type, k))

cur.execute("""
    UPDATE questions
    SET learning_outcome_id = (
            SELECT lessons.outcome_id
            FROM assessments
            JOIN lessons ON lessons.lesson_id = assessments.lesson_id
            WHERE assessments.assessment_id = questions.assessment_id
        ),
        competency_id = (
            SELECT lo.competency_id
            FROM assessments
            JOIN lessons ON lessons.lesson_id = assessments.lesson_id
            JOIN learning_outcomes lo ON lo.outcome_id = lessons.outcome_id
            WHERE assessments.assessment_id = questions.assessment_id
        ),
        topic_id = (
            SELECT lo.topic_id
            FROM assessments
            JOIN lessons ON lessons.lesson_id = assessments.lesson_id
            JOIN learning_outcomes lo ON lo.outcome_id = lessons.outcome_id
            WHERE assessments.assessment_id = questions.assessment_id
        ),
        subject_id = (
            SELECT c.subject_id
            FROM assessments
            JOIN lessons ON lessons.lesson_id = assessments.lesson_id
            JOIN learning_outcomes lo ON lo.outcome_id = lessons.outcome_id
            JOIN competencies c ON c.competency_id = lo.competency_id
            WHERE assessments.assessment_id = questions.assessment_id
        ),
        concept_id = (
            SELECT concepts.concept_id
            FROM assessments
            JOIN lessons ON lessons.lesson_id = assessments.lesson_id
            JOIN concepts ON concepts.outcome_id = lessons.outcome_id
                AND concepts.concept_tag = questions.concept_tag
            WHERE assessments.assessment_id = questions.assessment_id
            LIMIT 1
        ),
        correct_answer = (
            SELECT option_text
            FROM question_options
            WHERE question_options.question_id = questions.question_id
              AND question_options.is_correct = 1
            LIMIT 1
        ),
        resource_link = resource_hint,
        estimated_time = estimated_time_minutes
""")

cached_rows = [
    ("course", ict_course, "Introduction to ICT offline packet", "course:ict:introduction", 512),
    ("course", phy_course, "Measurements in Physics offline packet", "course:physics:measurements", 640),
    ("static", None, "Core offline service worker", "static:service-worker", 32),
]
for resource_type, resource_id, title, cache_key, size_kb in cached_rows:
    cur.execute("""
        INSERT INTO cached_resources
        (resource_type, resource_id, resource_title, cache_key, cache_status, estimated_size_kb)
        SELECT ?, ?, ?, ?, 'Cached', ?
        WHERE NOT EXISTS (SELECT 1 FROM cached_resources WHERE cache_key=?)
    """, (resource_type, resource_id, title, cache_key, size_kb, cache_key))

cur.execute("""
    INSERT INTO offline_sync_queue (learner_id, event_type, payload, sync_status)
    SELECT ?, 'offline_foundation_demo', '{"message":"Prototype queued event for low-resource readiness"}', 'Pending'
    WHERE NOT EXISTS (SELECT 1 FROM offline_sync_queue WHERE event_type='offline_foundation_demo')
""", (learner_id,))

cur.execute("""
    INSERT INTO activity_logs (learner_id, activity_type, activity_description)
    VALUES (?, ?, ?)
""", (learner_id, "System Setup", "Adaptive mastery pathway loaded: pre-test, adaptive notes, video support, practice, post-test, mastery decision, and locked progression."))

conn.commit()
conn.close()

print("===================================")
print("Learn2Master Adaptive Mastery Seed Loaded")
print("Learner: elijah / 12345")
print("Teacher: teacher / 12345")
print("School Administrator: admin / 12345")
print("Super Administrator: superadmin / 12345")
print("===================================")
