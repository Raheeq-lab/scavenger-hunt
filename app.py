from flask import Flask, render_template, request, redirect, url_for, session, jsonify, flash
from flask_sqlalchemy import SQLAlchemy
from flask_bcrypt import Bcrypt
import os
from datetime import datetime
import random
import json
import uuid

app = Flask(__name__)

# Configuration for Render
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///scavenger_hunt.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Initialize extensions
db = SQLAlchemy(app)
bcrypt = Bcrypt(app)

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
    question_type = db.Column(db.String(50), nullable=False)  # multiple-choice, text
    text = db.Column(db.Text, nullable=False)
    choices = db.Column(db.Text)  # JSON string for multiple choice
    correct_answer = db.Column(db.Text, nullable=False)
    hint = db.Column(db.Text)  # Hint for THIS location
    next_location_hint = db.Column(db.Text)  # Hint for NEXT location
    qr_token = db.Column(db.String(100), unique=True)
    points = db.Column(db.Integer, default=10)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

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

# NEW ROUTE: This is what your frontend is trying to call
@app.route("/teacher/create-hunt-with-questions", methods=['POST'])
def create_hunt_with_questions():
    if 'user_type' not in session or session['user_type'] != 'teacher':
        return jsonify({'success': False, 'error': 'Not logged in'}), 401
    
    try:
        # DEBUG: Print all form data
        print("=== DEBUG: FORM DATA ===")
        for key, value in request.form.items():
            print(f"{key}: {value}")
        print("========================")
        
        # Get the data from the form
        hunt_name = request.form.get('huntName', '').strip()
        questions_data = request.form.get('questions', '[]')
        
        print(f"DEBUG: hunt_name = '{hunt_name}'")
        print(f"DEBUG: questions_data (first 500 chars) = '{questions_data[:500]}'")
        
        if not hunt_name:
            return jsonify({'success': False, 'error': 'Hunt name is required'}), 400
        
        # Parse questions data
        try:
            questions = json.loads(questions_data)
            print(f"DEBUG: Parsed {len(questions)} questions")
        except json.JSONDecodeError as e:
            print(f"DEBUG: JSON Parse Error: {e}")
            return jsonify({'success': False, 'error': 'Invalid questions format'}), 400
        
        # Create the hunt
        teacher_id = session['user_id']
        hunt = Hunt(
            name=hunt_name,
            teacher_id=teacher_id,
            description=f"Scavenger hunt created on {datetime.now().strftime('%Y-%m-%d')}",
            is_active=False
        )
        db.session.add(hunt)
        db.session.commit()
        
        print(f"DEBUG: Created hunt with ID {hunt.id}")
        
        # Add questions to the hunt
        question_count = 0
        for i, q_data in enumerate(questions, 1):
            question_type = q_data.get('type', 'text')
            text = q_data.get('text', '').strip()
            correct_answer = q_data.get('answer', '').strip()
            hint = q_data.get('hint', '').strip()
            next_location_hint = q_data.get('nextLocationHint', '').strip()
            points = int(q_data.get('points', 10))
            
            if not text or not correct_answer:
                print(f"DEBUG: Skipping question {i} - missing text or answer")
                continue  # Skip invalid questions
            
            print(f"DEBUG: Adding question {i}: {text[:50]}...")
            
            # Process choices for multiple-choice
            choices = []
            if question_type == 'multiple-choice':
                choices = q_data.get('choices', [])
                # Ensure we have exactly 4 choices
                while len(choices) < 4:
                    choices.append('')
            
            question = Question(
                hunt_id=hunt.id,
                question_order=i,
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
            question_count += 1
        
        db.session.commit()
        
        print(f"DEBUG: Successfully created hunt with {question_count} questions")
        
        return jsonify({
            'success': True,
            'message': 'Hunt created successfully!',
            'hunt_id': hunt.id,
            'redirect_url': url_for('view_hunt', hunt_id=hunt.id)
        })
        
    except Exception as e:
        db.session.rollback()
        print(f"DEBUG: ERROR: {str(e)}")
        import traceback
        print(f"DEBUG: TRACEBACK: {traceback.format_exc()}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

# Keep the old create-hunt route for backward compatibility
@app.route("/teacher/create-hunt", methods=['GET'])
def create_hunt():
    if 'user_type' not in session or session['user_type'] != 'teacher':
        return redirect(url_for('teacher_login'))
    
    return render_template('create_hunt.html')

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
            'text': question.text,
            'hint': question.hint,
            'next_location_hint': question.next_location_hint,
            'qr_token': question.qr_token,
            'qr_url': qr_url,
            'qr_text': qr_text,
            'is_last': question.question_order == len(hunt.questions)
        })
    
    # Sort by question order
    questions.sort(key=lambda x: x['order'])
    
    return render_template('view_hunt.html', 
                         hunt=hunt, 
                         questions=questions)

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

# Student Routes
@app.route("/student/dashboard")
def student_dashboard():
    if 'student_id' not in session:
        session['student_id'] = str(uuid.uuid4())
        session['student_name'] = f"Student_{random.randint(1000, 9999)}"
        session['progress'] = {}
    
    active_hunts = Hunt.query.filter_by(is_active=True).all()
    return render_template('student_dashboard.html',
                         student_name=session.get('student_name'),
                         active_hunts=active_hunts)

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
    
    return render_template('student_question.html',
                         question=question,
                         hunt=hunt,
                         choices=json.loads(question.choices) if question.choices else [],
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
            'started_at': datetime.utcnow().isoformat()
        }
    
    progress = session['progress'][hunt_id_str]
    
    # Check answer
    is_correct = False
    if question.question_type == 'multiple-choice':
        is_correct = answer == question.correct_answer
    elif question.question_type == 'text':
        is_correct = answer.lower().strip() == question.correct_answer.lower().strip()
    
    # Update progress
    if qr_token not in progress['completed_questions']:
        progress['completed_questions'].append(qr_token)
        if is_correct:
            progress['score'] += question.points
            progress['current_question'] = question.question_order + 1
    
    session.modified = True
    
    # Get next question
    next_question = Question.query.filter_by(
        hunt_id=question.hunt_id, 
        question_order=question.question_order + 1
    ).first()
    
    response = {
        'success': True,
        'correct': is_correct,
        'points_earned': question.points if is_correct else 0,
        'total_score': progress['score'],
        'hint': question.hint if is_correct else None,
        'next_location_hint': next_question.next_location_hint if next_question and is_correct else None,
        'next_qr_token': next_question.qr_token if next_question else None,
        'has_next': next_question is not None,
        'is_last_question': next_question is None,
        'completion_message': "🎉 Congratulations! You've completed the entire hunt!" if not next_question and is_correct else None
    }
    
    return jsonify(response)

@app.route("/student/progress/<int:hunt_id>")
def student_progress(hunt_id):
    if 'student_id' not in session:
        return redirect(url_for('student_dashboard'))
    
    hunt = Hunt.query.get_or_404(hunt_id)
    progress = session.get('progress', {}).get(str(hunt_id), {})
    
    return render_template('student_progress.html',
                         hunt=hunt,
                         progress=progress,
                         total_questions=len(hunt.questions))

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

# Initialize database
with app.app_context():
    db.create_all()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
