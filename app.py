from flask import Flask, render_template, request, redirect, url_for, session, jsonify, send_file, flash
from flask_sqlalchemy import SQLAlchemy
from flask_bcrypt import Bcrypt
import qrcode
import os
from werkzeug.utils import secure_filename
from datetime import datetime, timedelta
import io
import random
import time
import json
import uuid
import socket

app = Flask(__name__)

# Configuration for Render
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///scavenger_hunt.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['QR_FOLDER'] = 'static/qr_codes'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size

# Initialize extensions
db = SQLAlchemy(app)
bcrypt = Bcrypt(app)

# Create necessary folders
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['QR_FOLDER'], exist_ok=True)

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
    question_type = db.Column(db.String(50), nullable=False)  # multiple-choice, text, image
    text = db.Column(db.Text, nullable=False)
    image = db.Column(db.String(200))
    choices = db.Column(db.Text)  # JSON string for multiple choice
    correct_answer = db.Column(db.Text, nullable=False)
    clue = db.Column(db.Text)
    qr_token = db.Column(db.String(100), unique=True)
    points = db.Column(db.Integer, default=10)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

# Helper Functions
def allowed_file(filename):
    ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def get_qr_url(qr_token):
    """Generate QR URL based on deployment environment"""
    base_url = os.environ.get('BASE_URL', request.host_url.rstrip('/'))
    return f"{base_url}/student/question/{qr_token}"

def generate_qr_code(qr_data, hunt_id, question_id):
    """Generate QR code and save to file - ROBUST VERSION"""
    try:
        filename = f"qr_{hunt_id}_{question_id}_{int(time.time())}.png"
        filepath = os.path.join(app.config['QR_FOLDER'], filename)
        
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=10,
            border=4,
        )
        qr.add_data(qr_data)
        qr.make(fit=True)
        
        # Try to generate image with Pillow
        try:
            img = qr.make_image(fill_color="black", back_color="white")
            img.save(filepath)
            return filename
        except Exception as pillow_error:
            print(f"Pillow error: {pillow_error}")
            # Fallback: Generate ASCII QR code
            ascii_qr = qr.get_matrix()
            ascii_file = filepath.replace('.png', '.txt')
            with open(ascii_file, 'w') as f:
                f.write(f"QR Code for URL: {qr_data}\n\n")
                for row in ascii_qr:
                    line = ''.join(['██' if cell else '  ' for cell in row])
                    f.write(line + '\n')
            return filename.replace('.png', '.txt')
            
    except Exception as e:
        print(f"QR Generation Error: {e}")
        return None

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
        
        # Check if teacher exists
        existing = Teacher.query.filter_by(email=email).first()
        if existing:
            flash('Email already registered', 'danger')
            return redirect(url_for('teacher_register'))
        
        # Create new teacher
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
        
        flash('Hunt created successfully!', 'success')
        return redirect(url_for('edit_hunt', hunt_id=hunt.id))
    
    return render_template('create_hunt.html')

@app.route("/teacher/hunt/<int:hunt_id>/edit")
def edit_hunt(hunt_id):
    if 'user_type' not in session or session['user_type'] != 'teacher':
        return redirect(url_for('teacher_login'))
    
    hunt = Hunt.query.get_or_404(hunt_id)
    if hunt.teacher_id != session['user_id']:
        flash('Access denied', 'danger')
        return redirect(url_for('teacher_dashboard'))
    
    return render_template('edit_hunt.html', hunt=hunt)

@app.route("/teacher/hunt/<int:hunt_id>/view")
def view_hunt(hunt_id):
    if 'user_type' not in session or session['user_type'] != 'teacher':
        return redirect(url_for('teacher_login'))
    
    hunt = Hunt.query.get_or_404(hunt_id)
    if hunt.teacher_id != session['user_id']:
        flash('Access denied', 'danger')
        return redirect(url_for('teacher_dashboard'))
    
    return render_template('view_hunt.html', hunt=hunt)

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
    
    # Initialize student session if needed
    if 'student_id' not in session:
        session['student_id'] = str(uuid.uuid4())
        session['student_name'] = f"Student_{random.randint(1000, 9999)}"
    
    return render_template('student_question.html',
                         question=question,
                         hunt=hunt)

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
    elif question.question_type == 'image':
        is_correct = True  # Accept any answer for image questions
    
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

# QR Code Routes - SIMPLIFIED VERSION
@app.route("/generate_qr/<int:hunt_id>/<int:question_id>")
def generate_qr(hunt_id, question_id):
    """Generate QR code - SIMPLIFIED FOR DEPLOYMENT"""
    try:
        question = Question.query.get_or_404(question_id)
        
        # Generate or get QR token
        if not question.qr_token:
            question.qr_token = str(uuid.uuid4())
            db.session.commit()
        
        qr_url = get_qr_url(question.qr_token)
        
        # Create simple QR code (text-based if Pillow fails)
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=10,
            border=4,
        )
        qr.add_data(qr_url)
        qr.make(fit=True)
        
        # Try to create image
        try:
            img = qr.make_image(fill_color="black", back_color="white")
            img_io = io.BytesIO()
            img.save(img_io, 'PNG')
            img_io.seek(0)
            return send_file(img_io, mimetype='image/png')
        except:
            # Return QR code as text
            return jsonify({
                'qr_url': qr_url,
                'qr_text': qr_url,
                'message': 'Copy this URL to any QR code generator',
                'ascii_qr': str(qr.get_matrix())
            })
            
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# Alternative QR endpoint that always works
@app.route("/qr_text/<int:hunt_id>/<int:question_id>")
def qr_text(hunt_id, question_id):
    """Get QR code URL as text (always works)"""
    question = Question.query.get_or_404(question_id)
    
    if not question.qr_token:
        question.qr_token = str(uuid.uuid4())
        db.session.commit()
    
    qr_url = get_qr_url(question.qr_token)
    
    return jsonify({
        'success': True,
        'qr_url': qr_url,
        'message': 'Use this URL with any QR code generator app'
    })

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
