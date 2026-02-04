from flask import Flask, render_template, request, redirect, url_for, session, jsonify, flash
from flask_sqlalchemy import SQLAlchemy
from flask_bcrypt import Bcrypt
from werkzeug.utils import secure_filename
import os
from datetime import datetime
import random
import json
import uuid
import re

app = Flask(__name__)

# Configuration for Render
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')

# Fix database URI for Render/Heroku
database_url = os.environ.get('DATABASE_URL', 'sqlite:///scavenger_hunt.db')
if database_url and database_url.startswith('postgres://'):
    database_url = database_url.replace('postgres://', 'postgresql://', 1)
app.config['SQLALCHEMY_DATABASE_URI'] = database_url

app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Session security
app.config['SESSION_COOKIE_SECURE'] = os.environ.get('FLASK_ENV') == 'production'
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

# File upload configuration
UPLOAD_FOLDER = 'static/uploads'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max

# Initialize extensions
db = SQLAlchemy(app)
bcrypt = Bcrypt(app)

# Create upload folder if it doesn't exist
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Database Models
class Teacher(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    school = db.Column(db.String(200))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    hunts = db.relationship('Hunt', backref='teacher', lazy=True)

class Hunt(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    teacher_id = db.Column(db.Integer, db.ForeignKey('teacher.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_active = db.Column(db.Boolean, default=False)
    questions = db.relationship('Question', backref='hunt', lazy=True, order_by='Question.question_order')

class Question(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    hunt_id = db.Column(db.Integer, db.ForeignKey('hunt.id'), nullable=False)
    question_order = db.Column(db.Integer, default=0)  # Order of questions
    question_type = db.Column(db.String(50), nullable=False)  # multiple-choice, text, image
    text = db.Column(db.Text, nullable=False)
    choices = db.Column(db.Text)  # JSON string for multiple choice
    correct_answer = db.Column(db.Text, nullable=False)
    hint = db.Column(db.Text)  # Hint for THIS location
    next_location_hint = db.Column(db.Text)  # Hint for NEXT location
    qr_token = db.Column(db.String(100), unique=True)
    points = db.Column(db.Integer, default=10)
    image_filename = db.Column(db.String(200))  # For image questions
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Submission(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    hunt_id = db.Column(db.Integer, db.ForeignKey('hunt.id'), nullable=False)
    student_name = db.Column(db.String(100), nullable=False)
    total_score = db.Column(db.Integer, default=0)
    max_score = db.Column(db.Integer, default=0)
    completed_questions = db.Column(db.Integer, default=0)
    total_questions = db.Column(db.Integer, default=0)
    marks_json = db.Column(db.Text)  # JSON string for per-question points
    completed_at = db.Column(db.DateTime, default=datetime.utcnow)

# Helper Functions
def get_qr_url(qr_token):
    """Generate QR URL"""
    base_url = request.host_url.rstrip('/')
    return f"{base_url}/student/question/{qr_token}"

def generate_qr_text(qr_token):
    """Generate text representation of QR code"""
    qr_url = get_qr_url(qr_token)
    return f"""
╔══════════════════════════════════════╗
║         SCAVENGER HUNT QR CODE       ║
╠══════════════════════════════════════╣
║ URL: {qr_url[:35]:<35} ║
║       {qr_url[35:]:<35} ║
╠══════════════════════════════════════╣
║  Scan this URL with any QR scanner   ║
║  Or visit directly:                  ║
║  {qr_url:<35} ║
╚══════════════════════════════════════╝
"""

# Routes
@app.route("/")
def home():
    if 'user_type' in session:
        if session['user_type'] == 'teacher':
            return redirect(url_for('teacher_dashboard'))
        elif session['user_type'] == 'student':
            return redirect(url_for('student_dashboard'))
    return render_template('index.html')

# Teacher Routes
@app.route("/teacher/register", methods=['GET', 'POST'])
def teacher_register():
    if request.method == 'POST':
        name = request.form['name']
        email = request.form['email']
        password = request.form['password']
        school = request.form.get('school', '')

        existing = Teacher.query.filter_by(email=email).first()
        if existing:
            flash('Email already registered', 'danger')
            return redirect(url_for('teacher_register'))

        hashed_password = bcrypt.generate_password_hash(password).decode('utf-8')
        teacher = Teacher(name=name, email=email, password=hashed_password, school=school)
        db.session.add(teacher)
        db.session.commit()

        flash('Registration successful! Please login.', 'success')
        return redirect(url_for('teacher_login'))

    return render_template('teacher_register.html')

@app.route("/teacher/login", methods=['GET', 'POST'])
def teacher_login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']

        teacher = Teacher.query.filter_by(email=email).first()

        if teacher and bcrypt.check_password_hash(teacher.password, password):
            session['user_id'] = teacher.id
            session['user_type'] = 'teacher'
            session['teacher_name'] = teacher.name

            flash('Login successful!', 'success')
            return redirect(url_for('teacher_dashboard'))
        else:
            flash('Invalid email or password', 'danger')

    return render_template('teacher_login.html')

@app.route("/teacher/dashboard")
def teacher_dashboard():
    if 'user_type' not in session or session['user_type'] != 'teacher':
        return redirect(url_for('teacher_login'))

    teacher_id = session['user_id']
    hunts = Hunt.query.filter_by(teacher_id=teacher_id).all()

    return render_template('teacher_dashboard.html',
                         teacher_name=session.get('teacher_name'),
                         hunts=hunts)

@app.route("/teacher/create-hunt", methods=['GET', 'POST'])
def create_hunt():
    if 'user_type' not in session or session['user_type'] != 'teacher':
        return redirect(url_for('teacher_login'))

    if request.method == 'POST':
        name = request.form['name']
        description = request.form.get('description', '')
        teacher_id = session['user_id']

        hunt = Hunt(name=name, description=description, teacher_id=teacher_id)
        db.session.add(hunt)
        db.session.commit()

        flash('Hunt created successfully! Now add questions.', 'success')
        return redirect(url_for('add_question', hunt_id=hunt.id))

    return render_template('create_hunt.html')

@app.route("/teacher/create-hunt-with-questions", methods=['POST'])
def create_hunt_with_questions():
    """Handle the new create hunt flow from JavaScript"""
    if 'user_type' not in session or session['user_type'] != 'teacher':
        return jsonify({'success': False, 'error': 'Not logged in'}), 401

    try:
        # Get JSON data
        data = request.get_json()

        if not data:
            return jsonify({'success': False, 'error': 'No data received'}), 400

        hunt_name = data.get('huntName', '').strip()
        hunt_description = data.get('huntDescription', '').strip()
        questions = data.get('questions', [])

        if not hunt_name:
            return jsonify({'success': False, 'error': 'Hunt name is required'}), 400

        # Create the hunt
        teacher_id = session['user_id']
        hunt = Hunt(
            name=hunt_name,
            description=hunt_description,
            teacher_id=teacher_id,
            is_active=False
        )
        db.session.add(hunt)
        db.session.commit()

        # Add questions to the hunt
        for i, q_data in enumerate(questions, 1):
            question_type = q_data.get('type', 'text')
            text = q_data.get('text', '').strip()
            correct_answer = q_data.get('answer', '').strip()
            next_location_hint = q_data.get('nextLocationHint', '').strip()
            points = int(q_data.get('points', 10))

            if not text or not correct_answer:
                continue

            # Process choices for multiple-choice
            choices = []
            if question_type == 'multiple-choice':
                choices = q_data.get('choices', [])
                # Ensure we have exactly 4 choices for database consistency
                while len(choices) < 4:
                    choices.append('')

            question = Question(
                hunt_id=hunt.id,
                question_order=i,
                question_type=question_type,
                text=text,
                choices=json.dumps(choices) if choices else '',
                correct_answer=correct_answer,
                hint='',  # Your form doesn't have a hint field
                next_location_hint=next_location_hint,
                qr_token=str(uuid.uuid4()),
                points=points
            )
            db.session.add(question)

        db.session.commit()

        return jsonify({
            'success': True,
            'message': 'Hunt created successfully!',
            'hunt_id': hunt.id,
            'redirect_url': url_for('view_hunt', hunt_id=hunt.id)
        })

    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route("/teacher/hunt/<int:hunt_id>/add-question", methods=['GET', 'POST'])
def add_question(hunt_id):
    if 'user_type' not in session or session['user_type'] != 'teacher':
        return redirect(url_for('teacher_login'))

    hunt = Hunt.query.get_or_404(hunt_id)
    if hunt.teacher_id != session['user_id']:
        flash('Access denied', 'danger')
        return redirect(url_for('teacher_dashboard'))

    if request.method == 'POST':
        question_type = request.form['question_type']
        text = request.form['text']
        correct_answer = request.form['correct_answer']
        hint = request.form.get('hint', '')
        next_location_hint = request.form.get('next_location_hint', '')
        points = int(request.form.get('points', 10))

        # Get next question order
        last_question = Question.query.filter_by(hunt_id=hunt_id).order_by(Question.question_order.desc()).first()
        next_order = last_question.question_order + 1 if last_question else 1

        # Process choices for multiple-choice
        choices = []
        if question_type == 'multiple-choice':
            choices = [
                request.form.get('choice1', ''),
                request.form.get('choice2', ''),
                request.form.get('choice3', ''),
                request.form.get('choice4', '')
            ]

        question = Question(
            hunt_id=hunt_id,
            question_order=next_order,
            question_type=question_type,
            text=text,
            choices=json.dumps(choices) if choices else '',
            correct_answer=correct_answer,
            hint=hint,
            next_location_hint=next_location_hint,
            qr_token=str(uuid.uuid4()),
            points=points
        )

        db.session.add(question)
        db.session.commit()

        flash(f'Question {next_order} added successfully!', 'success')
        return redirect(url_for('view_hunt', hunt_id=hunt_id))

    return render_template('add_question.html', hunt=hunt)

@app.route("/teacher/hunt/<int:hunt_id>/view")
def view_hunt(hunt_id):
    if 'user_type' not in session or session['user_type'] != 'teacher':
        return redirect(url_for('teacher_login'))

    hunt = Hunt.query.get_or_404(hunt_id)
    if hunt.teacher_id != session['user_id']:
        flash('Access denied', 'danger')
        return redirect(url_for('teacher_dashboard'))

    # Get all questions with QR info
    questions = []
    for question in hunt.questions:
        qr_url = get_qr_url(question.qr_token)
        qr_text = generate_qr_text(question.qr_token)

        questions.append({
            'id': question.id,
            'order': question.question_order,
            'type': question.question_type,
            'text': question.text,
            'hint': question.hint,
            'next_location_hint': question.next_location_hint,
            'qr_token': question.qr_token,
            'qr_url': qr_url,
            'qr_text': qr_text,
            'points': question.points,
            'is_last': question.question_order == len(hunt.questions)
        })

    # Sort by question order
    questions.sort(key=lambda x: x['order'])

    return render_template('view_hunt.html',
                         hunt=hunt,
                         questions=questions)

@app.route("/teacher/hunt/<int:hunt_id>/results")
def hunt_results(hunt_id):
    if 'user_type' not in session or session['user_type'] != 'teacher':
        return redirect(url_for('teacher_login'))

    hunt = Hunt.query.get_or_404(hunt_id)
    if hunt.teacher_id != session['user_id']:
        flash('Access denied', 'danger')
        return redirect(url_for('teacher_dashboard'))

    submissions = Submission.query.filter_by(hunt_id=hunt_id).order_by(Submission.completed_at.desc()).all()

    # Pre-process marks for each submission if needed
    for sub in submissions:
        if sub.marks_json:
            try:
                sub.marks = json.loads(sub.marks_json)
            except:
                sub.marks = {}
        else:
            sub.marks = {}

    return render_template('teacher_hunt_results.html', hunt=hunt, submissions=submissions)

@app.route("/teacher/hunt/<int:hunt_id>/toggle-active", methods=['POST'])
def toggle_hunt_active(hunt_id):
    if 'user_type' not in session or session['user_type'] != 'teacher':
        return jsonify({'error': 'Not logged in'}), 401

    hunt = Hunt.query.get_or_404(hunt_id)
    if hunt.teacher_id != session['user_id']:
        return jsonify({'error': 'Access denied'}), 403

    hunt.is_active = not hunt.is_active
    db.session.commit()

    status = "active" if hunt.is_active else "inactive"
    return jsonify({'success': True, 'is_active': hunt.is_active, 'message': f'Hunt is now {status}'})

@app.route("/teacher/hunt/<int:hunt_id>/delete", methods=['DELETE'])
def delete_hunt(hunt_id):
    if 'user_type' not in session or session['user_type'] != 'teacher':
        return jsonify({'success': False, 'error': 'Not logged in'}), 401

    hunt = Hunt.query.get_or_404(hunt_id)
    if hunt.teacher_id != session['user_id']:
        return jsonify({'success': False, 'error': 'Access denied'}), 403

    try:
        # Delete all questions first
        Question.query.filter_by(hunt_id=hunt_id).delete()
        # Delete the hunt
        db.session.delete(hunt)
        db.session.commit()
        return jsonify({'success': True, 'message': 'Hunt deleted successfully'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route("/teacher/hunt/<int:hunt_id>/edit", methods=['GET', 'POST'])
def edit_hunt(hunt_id):
    if 'user_type' not in session or session['user_type'] != 'teacher':
        return redirect(url_for('teacher_login'))

    hunt = Hunt.query.get_or_404(hunt_id)
    if hunt.teacher_id != session['user_id']:
        flash('Access denied', 'danger')
        return redirect(url_for('teacher_dashboard'))

    if request.method == 'POST':
        hunt.name = request.form['name']
        hunt.description = request.form.get('description', '')

        db.session.commit()
        flash('Hunt updated successfully!', 'success')
        return redirect(url_for('view_hunt', hunt_id=hunt.id))

    return render_template('edit_hunt.html', hunt=hunt)


@app.route("/teacher/question/<int:question_id>/edit", methods=['GET', 'POST'])
def edit_question(question_id):
    if 'user_type' not in session or session['user_type'] != 'teacher':
        return redirect(url_for('teacher_login'))

    question = Question.query.get_or_404(question_id)
    hunt = Hunt.query.get(question.hunt_id)

    if hunt.teacher_id != session['user_id']:
        flash('Access denied', 'danger')
        return redirect(url_for('teacher_dashboard'))

    if request.method == 'POST':
        question.question_type = request.form['question_type']
        question.text = request.form['text']
        question.correct_answer = request.form['correct_answer']
        question.hint = request.form.get('hint', '')
        question.next_location_hint = request.form.get('next_location_hint', '')
        question.points = int(request.form.get('points', 10))

        # Process choices for multiple-choice
        if question.question_type == 'multiple-choice':
            choices = [
                request.form.get('choice1', ''),
                request.form.get('choice2', ''),
                request.form.get('choice3', ''),
                request.form.get('choice4', '')
            ]
            question.choices = json.dumps(choices)
        else:
            question.choices = ''

        db.session.commit()
        flash('Question updated successfully!', 'success')
        return redirect(url_for('view_hunt', hunt_id=hunt.id))

    # Parse choices for multiple-choice
    choices = []
    if question.choices:
        try:
            choices = json.loads(question.choices)
        except:
            choices = []

    return render_template('edit_question.html', question=question, hunt=hunt, choices=choices)


# Student Routes
@app.route("/student/dashboard")
def student_dashboard():
    if 'student_id' not in session:
        session['student_id'] = str(uuid.uuid4())
        session['student_name'] = f"Student_{random.randint(1000, 9999)}"
        session['progress'] = {}

    active_hunts = Hunt.query.filter_by(is_active=True).all()

    # Get started hunts from session
    started_hunts = {}
    if 'progress' in session:
        for hunt_id_str, progress in session['progress'].items():
            try:
                hunt_id = int(hunt_id_str)
                hunt = Hunt.query.get(hunt_id)
                if hunt and hunt.is_active:
                    # Get current question token
                    current_q_order = progress.get('current_question', 1)
                    current_question = Question.query.filter_by(
                        hunt_id=hunt_id,
                        question_order=current_q_order
                    ).first()

                    started_hunts[hunt_id] = {
                        'hunt_name': hunt.name,
                        'score': progress.get('score', 0),
                        'completed_questions': progress.get('completed_questions', []),
                        'current_question_token': current_question.qr_token if current_question else None
                    }
            except:
                continue

    return render_template('student_dashboard.html',
                         student_name=session.get('student_name'),
                         active_hunts=active_hunts,
                         started_hunts=started_hunts)

@app.route("/student/start-hunt/<int:hunt_id>")
def start_hunt(hunt_id):
    if 'student_id' not in session:
        session['student_id'] = str(uuid.uuid4())
        session['student_name'] = f"Student_{random.randint(1000, 9999)}"
        session['progress'] = {}

    hunt = Hunt.query.filter_by(id=hunt_id, is_active=True).first()
    if not hunt:
        flash('Hunt not found or not active', 'danger')
        return redirect(url_for('student_dashboard'))

    # Initialize progress for this hunt
    if str(hunt_id) not in session['progress']:
        session['progress'][str(hunt_id)] = {
            'current_question': 1,
            'score': 0,
            'completed_questions': [],
            'started_at': datetime.utcnow().isoformat()
        }
        session.modified = True

    # Get first question
    first_question = Question.query.filter_by(hunt_id=hunt_id, question_order=1).first()
    if not first_question:
        flash('This hunt has no questions yet', 'warning')
        return redirect(url_for('student_dashboard'))

    return redirect(url_for('student_question', qr_token=first_question.qr_token))

@app.route("/student/question/<qr_token>")
def student_question(qr_token):
    question = Question.query.filter_by(qr_token=qr_token).first()
    if not question:
        return render_template('error.html',
                             message='Invalid QR code',
                             details='This QR code does not match any question.')

    hunt = Hunt.query.get(question.hunt_id)

    if not hunt.is_active:
        return render_template('error.html',
                             message='Hunt not active',
                             details='This hunt is currently not active.')

    if 'student_id' not in session:
        session['student_id'] = str(uuid.uuid4())
        session['student_name'] = f"Student_{random.randint(1000, 9999)}"
        session['progress'] = {}

    # Get next question info
    next_question = Question.query.filter_by(
        hunt_id=question.hunt_id,
        question_order=question.question_order + 1
    ).first()

    # Parse choices for multiple-choice
    choices = []
    if question.choices:
        try:
            choices = json.loads(question.choices)
            # Filter out empty choices
            choices = [choice for choice in choices if choice and choice.strip()]
        except:
            choices = []

    return render_template('student_question.html',
                         question=question,
                         hunt=hunt,
                         choices=choices,
                         next_question=next_question)

@app.route("/api/student/submit-answer", methods=['POST'])
def submit_answer():
    data = request.json
    qr_token = data.get('qr_token')
    answer = data.get('answer')
    student_name = data.get('student_name', '')

    if not qr_token or answer is None:
        return jsonify({'error': 'Missing required fields'}), 400

    # Update student name if provided
    if student_name and 'student_name' in session:
        session['student_name'] = student_name

    question = Question.query.filter_by(qr_token=qr_token).first()
    if not question:
        return jsonify({'error': 'Question not found'}), 404

    hunt = Hunt.query.get(question.hunt_id)

    # Initialize student progress
    hunt_id_str = str(question.hunt_id)
    if 'progress' not in session:
        session['progress'] = {}
    if hunt_id_str not in session['progress']:
        session['progress'][hunt_id_str] = {
            'current_question': question.question_order,
            'score': 0,
            'completed_questions': [],
            'attempts': {},
            'marks': {},
            'started_at': datetime.utcnow().isoformat()
        }

    progress = session['progress'][hunt_id_str]
    if 'attempts' not in progress:
        progress['attempts'] = {}
    if 'marks' not in progress:
        progress['marks'] = {}

    # Check if already completed
    if qr_token in progress.get('completed_questions', []):
        return jsonify({
            'success': True,
            'correct': True,
            'points_earned': 0,
            'message': 'Question already completed',
            'total_score': progress['score']
        })

    # Increment attempts for this question
    current_attempts = progress['attempts'].get(qr_token, 0) + 1
    progress['attempts'][qr_token] = current_attempts

    # Check answer
    is_correct = False
    if question.question_type == 'multiple-choice':
        is_correct = answer.lower().strip() == question.correct_answer.lower().strip()
    elif question.question_type == 'text':
        is_correct = answer.lower().strip() == question.correct_answer.lower().strip()
    elif question.question_type == 'image':
        # For image questions, any uploaded image is considered correct
        is_correct = True

    # Update progress
    points_earned = 0
    if is_correct:
        if qr_token not in progress['completed_questions']:
            # Point degradation logic:
            # 1st attempt: 100%
            # 2nd attempt: 50%
            # 3rd attempt: 10%
            # 4th+ attempt: 0%
            if current_attempts == 1:
                multiplier = 1.0
            elif current_attempts == 2:
                multiplier = 0.5
            elif current_attempts == 3:
                multiplier = 0.1
            else:
                multiplier = 0.0

            points_earned = int(question.points * multiplier)
            progress['completed_questions'].append(qr_token)
            progress['score'] += points_earned
            progress['marks'][qr_token] = points_earned
            progress['current_question'] = question.question_order + 1

    session.modified = True

    # Get next question
    next_question = Question.query.filter_by(
        hunt_id=question.hunt_id,
        question_order=question.question_order + 1
    ).first()

    # Detect completion and save to database
    if is_correct and not next_question:
        try:
            total_questions = len(hunt.questions)
            max_score = sum([q.points for q in hunt.questions])

            submission = Submission(
                hunt_id=hunt.id,
                student_name=session.get('student_name', 'Anonymous Student'),
                total_score=progress['score'],
                max_score=max_score,
                completed_questions=len(progress['completed_questions']),
                total_questions=total_questions,
                marks_json=json.dumps(progress.get('marks', {}))
            )
            db.session.add(submission)
            db.session.commit()
        except Exception as e:
            print(f"Error saving submission: {e}")
            db.session.rollback()

    response = {
        'success': True,
        'correct': is_correct,
        'points_earned': points_earned,
        'attempts': current_attempts,
        'total_score': progress['score'],
        'hint': question.hint if not is_correct else None,
        'next_location_hint': question.next_location_hint if is_correct else None,
        'next_qr_token': next_question.qr_token if next_question else None,
        'has_next': next_question is not None,
        'is_last_question': next_question is None,
        'completion_message': "🎉 Congratulations! You've completed the entire hunt!" if not next_question and is_correct else None
    }

    return jsonify(response)

@app.route("/api/student/submit-image", methods=['POST'])
def submit_image():
    """Handle image upload submissions"""
    if 'image' not in request.files:
        return jsonify({'error': 'No image uploaded'}), 400

    image_file = request.files['image']
    qr_token = request.form.get('qr_token')

    if image_file.filename == '':
        return jsonify({'error': 'No image selected'}), 400

    # Validate file type
    allowed_extensions = {'png', 'jpg', 'jpeg', 'gif'}
    filename = secure_filename(image_file.filename)
    if '.' not in filename or filename.rsplit('.', 1)[1].lower() not in allowed_extensions:
        return jsonify({'error': 'Invalid file type. Allowed: PNG, JPG, JPEG, GIF'}), 400

    # Validate file size (max 5MB)
    image_file.seek(0, 2)  # Seek to end
    file_size = image_file.tell()
    image_file.seek(0)  # Reset to beginning
    if file_size > 5 * 1024 * 1024:
        return jsonify({'error': 'File too large. Maximum size is 5MB'}), 400

    # Save the file
    unique_filename = f"{uuid.uuid4()}_{filename}"
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], unique_filename)
    image_file.save(filepath)

    # Get question and update progress
    question = Question.query.filter_by(qr_token=qr_token).first()
    if not question:
        # Delete the uploaded file if question not found
        os.remove(filepath)
        return jsonify({'error': 'Question not found'}), 404

    # For image questions, store the filename
    question.image_filename = unique_filename
    db.session.commit()

    # Initialize or update student progress
    hunt_id_str = str(question.hunt_id)
    if 'progress' not in session:
        session['progress'] = {}
    if hunt_id_str not in session['progress']:
        session['progress'][hunt_id_str] = {
            'current_question': question.question_order,
            'score': 0,
            'completed_questions': [],
            'attempts': {},
            'marks': {},
            'started_at': datetime.utcnow().isoformat()
        }

    progress = session['progress'][hunt_id_str]
    if 'attempts' not in progress:
        progress['attempts'] = {}
    if 'marks' not in progress:
        progress['marks'] = {}

    # Increment attempts for this question
    current_attempts = progress['attempts'].get(qr_token, 0) + 1
    progress['attempts'][qr_token] = current_attempts

    # For image questions, always count as correct
    points_earned = 0
    if qr_token not in progress['completed_questions']:
        # Point degradation logic:
        # 1st attempt: 100%
        # 2nd attempt: 50%
        # 3rd attempt: 10%
        # 4th+ attempt: 0%
        if current_attempts == 1:
            multiplier = 1.0
        elif current_attempts == 2:
            multiplier = 0.5
        elif current_attempts == 3:
            multiplier = 0.1
        else:
            multiplier = 0.0

        points_earned = int(question.points * multiplier)
        progress['completed_questions'].append(qr_token)
        progress['score'] += points_earned
        progress['marks'][qr_token] = points_earned
        progress['current_question'] = question.question_order + 1

    session.modified = True

    # Get next question
    next_question = Question.query.filter_by(
        hunt_id=question.hunt_id,
        question_order=question.question_order + 1
    ).first()

    # Detect completion and save to database
    if not next_question:
        try:
            hunt = Hunt.query.get(question.hunt_id)
            total_questions = len(hunt.questions)
            max_score = sum([q.points for q in hunt.questions])

            submission = Submission(
                hunt_id=hunt.id,
                student_name=session.get('student_name', 'Anonymous Student'),
                total_score=progress['score'],
                max_score=max_score,
                completed_questions=len(progress['completed_questions']),
                total_questions=total_questions,
                marks_json=json.dumps(progress.get('marks', {}))
            )
            db.session.add(submission)
            db.session.commit()
        except Exception as e:
            print(f"Error saving submission: {e}")
            db.session.rollback()

    return jsonify({
        'success': True,
        'correct': True,
        'points_earned': points_earned,
        'attempts': current_attempts,
        'image_url': f"/static/uploads/{unique_filename}",
        'next_location_hint': question.next_location_hint,
        'next_qr_token': next_question.qr_token if next_question else None,
        'has_next': next_question is not None
    })

@app.route("/student/progress/<int:hunt_id>")
def student_progress(hunt_id):
    if 'student_id' not in session:
        return redirect(url_for('student_dashboard'))

    hunt = Hunt.query.get_or_404(hunt_id)
    progress = session.get('progress', {}).get(str(hunt_id), {})

    return render_template('student_progress.html',
                         hunt=hunt,
                         progress=progress,
                         total_questions=len(hunt.questions),
                         now=datetime.utcnow())

# QR Display Page
@app.route("/qr/display/<qr_token>")
def display_qr(qr_token):
    question = Question.query.filter_by(qr_token=qr_token).first()
    if not question:
        return "Invalid QR code", 404

    qr_url = get_qr_url(qr_token)
    hunt = Hunt.query.get(question.hunt_id)

    return render_template('display_qr.html',
                         question=question,
                         hunt=hunt,
                         qr_url=qr_url,
                         qr_text=generate_qr_text(qr_token))

# Logout
@app.route("/logout")
def logout():
    session.clear()
    flash('Logged out successfully', 'info')
    return redirect(url_for('home'))

# Error handlers
@app.errorhandler(404)
def not_found_error(error):
    return render_template('error.html',
                         message='Page Not Found',
                         details='The page you are looking for does not exist.'), 404

@app.errorhandler(500)
def internal_error(error):
    db.session.rollback()
    return render_template('error.html',
                         message='Internal Server Error',
                         details='Something went wrong on our end.'), 500

# Initialize database
with app.app_context():
    db.create_all()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
