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
    questions = db.relationship('Question', backref='hunt', lazy=True)

class Question(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    hunt_id = db.Column(db.Integer, db.ForeignKey('hunt.id'), nullable=False)
    question_type = db.Column(db.String(50), nullable=False)  # multiple-choice, text
    text = db.Column(db.Text, nullable=False)
    choices = db.Column(db.Text)  # JSON string for multiple choice
    correct_answer = db.Column(db.Text, nullable=False)
    clue = db.Column(db.Text)
    qr_token = db.Column(db.String(100), unique=True)
    points = db.Column(db.Integer, default=10)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

# Helper Functions
def get_qr_url(qr_token):
    """Generate QR URL"""
    base_url = request.host_url.rstrip('/')
    return f"{base_url}/student/question/{qr_token}"

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
        
        # Create sample questions
        for i in range(3):
            question = Question(
                hunt_id=hunt.id,
                question_type='multiple-choice',
                text=f'Sample question {i+1}?',
                choices=json.dumps(['Option A', 'Option B', 'Option C', 'Option D']),
                correct_answer='Option A',
                clue=f'Clue for question {i+1}',
                qr_token=str(uuid.uuid4()),
                points=10
            )
            db.session.add(question)
        db.session.commit()
        
        flash('Hunt created successfully with 3 sample questions!', 'success')
        return redirect(url_for('view_hunt', hunt_id=hunt.id))
    
    return render_template('create_hunt.html')

@app.route("/teacher/hunt/<int:hunt_id>/view")
def view_hunt(hunt_id):
    if 'user_type' not in session or session['user_type'] != 'teacher':
        return redirect(url_for('teacher_login'))
    
    hunt = Hunt.query.get_or_404(hunt_id)
    if hunt.teacher_id != session['user_id']:
        flash('Access denied', 'danger')
        return redirect(url_for('teacher_dashboard'))
    
    # Get QR URLs for each question
    questions_with_qr = []
    for question in hunt.questions:
        qr_url = get_qr_url(question.qr_token)
        questions_with_qr.append({
            'id': question.id,
            'text': question.text,
            'qr_token': question.qr_token,
            'qr_url': qr_url,
            'qr_text': f"URL: {qr_url}\nScan with any QR code app"
        })
    
    return render_template('view_hunt.html', 
                         hunt=hunt, 
                         questions=questions_with_qr)

# Student Routes
@app.route("/student/dashboard")
def student_dashboard():
    if 'student_id' not in session:
        session['student_id'] = str(uuid.uuid4())
        session['student_name'] = f"Student_{random.randint(1000, 9999)}"
    
    active_hunts = Hunt.query.filter_by(is_active=True).all()
    return render_template('student_dashboard.html',
                         student_name=session.get('student_name'),
                         active_hunts=active_hunts)

@app.route("/student/question/<qr_token>")
def student_question(qr_token):
    question = Question.query.filter_by(qr_token=qr_token).first()
    if not question:
        return render_template('error.html',
                             message='Invalid QR code',
                             details='This QR code does not match any question.')
    
    hunt = Hunt.query.get(question.hunt_id)
    
    if 'student_id' not in session:
        session['student_id'] = str(uuid.uuid4())
        session['student_name'] = f"Student_{random.randint(1000, 9999)}"
    
    return render_template('student_question.html',
                         question=question,
                         hunt=hunt,
                         choices=json.loads(question.choices) if question.choices else [])

@app.route("/api/student/submit-answer", methods=['POST'])
def submit_answer():
    data = request.json
    qr_token = data.get('qr_token')
    answer = data.get('answer')
    
    if not qr_token or answer is None:
        return jsonify({'error': 'Missing required fields'}), 400
    
    question = Question.query.filter_by(qr_token=qr_token).first()
    if not question:
        return jsonify({'error': 'Question not found'}), 404
    
    # Check answer
    is_correct = False
    if question.question_type == 'multiple-choice':
        is_correct = answer == question.correct_answer
    elif question.question_type == 'text':
        is_correct = answer.lower().strip() == question.correct_answer.lower().strip()
    
    # Get next question
    next_question = Question.query.filter(
        Question.hunt_id == question.hunt_id,
        Question.id > question.id
    ).order_by(Question.id).first()
    
    response = {
        'success': True,
        'correct': is_correct,
        'points_earned': question.points if is_correct else 0,
        'clue': question.clue if is_correct else None,
        'next_qr_token': next_question.qr_token if next_question else None,
        'has_next': next_question is not None
    }
    
    return jsonify(response)

# Simple QR display (no image generation)
@app.route("/qr/<qr_token>")
def show_qr(qr_token):
    question = Question.query.filter_by(qr_token=qr_token).first()
    if not question:
        return "Invalid QR code", 404
    
    qr_url = get_qr_url(qr_token)
    
    # Return simple HTML with QR URL
    return f"""
    <html>
    <head><title>QR Code for Question</title></head>
    <body style="font-family: Arial; text-align: center; padding: 50px;">
        <h1>Scavenger Hunt Question</h1>
        <h3>{question.text[:100]}...</h3>
        <p><strong>QR Code URL:</strong></p>
        <div style="background: #f0f0f0; padding: 20px; margin: 20px; border-radius: 10px;">
            <code style="font-size: 18px;">{qr_url}</code>
        </div>
        <p>Copy this URL and use any QR code generator app to create a QR code.</p>
        <p>Or scan this page directly if your device supports it.</p>
        <a href="{qr_url}">Click here to go directly to the question</a>
    </body>
    </html>
    """

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
