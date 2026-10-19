"""
Campus QR Attendance System
===========================
A full-stack Flask application for college campuses.
Faculty create courses and start timed QR-code attendance sessions.
Students scan QR codes with their mobile devices to mark attendance in real time.

Tech Stack:
- Flask & Flask-SQLAlchemy (SQLite database)
- Flask-Login & Werkzeug security (Authentication & Password hashing)
- qrcode & Pillow (QR code generation)
- Jinja2 & Bootstrap 5 (Responsive mobile UI)
"""

import os
import io
import csv
import socket
import secrets
from datetime import datetime, timedelta, timezone
from functools import wraps
from urllib.parse import urlparse, urljoin

from flask import (
    Flask, render_template, redirect, url_for,
    flash, request, abort, send_file, Response, jsonify
)
from flask_sqlalchemy import SQLAlchemy
from flask_login import (
    LoginManager, UserMixin, login_user,
    login_required, logout_user, current_user
)
from werkzeug.security import generate_password_hash, check_password_hash
import qrcode

# -------------------------------------------------------------------
# Application Configuration
# -------------------------------------------------------------------
app = Flask(__name__)

# Configurable constants (can be overridden via environment variables)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'campus-qr-attendance-secret-key-2026')
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///attendance.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Session expiry in minutes (default 5 minutes)
SESSION_EXPIRY_MINUTES = int(os.environ.get('SESSION_EXPIRY_MINUTES', 5))

# Low attendance alert threshold in percent (default 75.0%)
ATTENDANCE_THRESHOLD = float(os.environ.get('ATTENDANCE_THRESHOLD', 75.0))

# Server port (default 5000)
SERVER_PORT = int(os.environ.get('PORT', 5000))

# Initialize database and login manager
db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'
login_manager.login_message = 'Please log in to access this page.'
login_manager.login_message_category = 'warning'


def utc_now():
    """
    Returns current UTC datetime as a timezone-naive datetime object.
    Ensures seamless compatibility with SQLite storage and Python 3.12+.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)



# -------------------------------------------------------------------
# Helper Utilities
# -------------------------------------------------------------------
def get_lan_ip():
    """
    Detect the local LAN IP address of this machine.
    Used so mobile devices connected to the same Wi-Fi network
    can access the QR scan URL instead of unreachable 'localhost'.
    """
    custom_host = os.environ.get('HOST_IP')
    if custom_host:
        return custom_host
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        # Doesn't need to be reachable, purely resolves default routing interface
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return '127.0.0.1'


def is_safe_url(target):
    """
    Ensures redirect URLs point only to relative paths or the same host.
    Prevents Open Redirect vulnerabilities (CWE-601).
    """
    ref_url = urlparse(request.host_url)
    test_url = urlparse(urljoin(request.host_url, target))
    return test_url.scheme in ('http', 'https') and ref_url.netloc == test_url.netloc


def faculty_required(f):
    """Decorator ensuring that only logged-in faculty can access the route."""
    @wraps(f)
    @login_required
    def decorated_function(*args, **kwargs):
        if not current_user.is_faculty():
            flash('Access denied. Faculty privileges required.', 'danger')
            return redirect(url_for('student_dashboard'))
        return f(*args, **kwargs)
    return decorated_function


def student_required(f):
    """Decorator ensuring that only logged-in students can access the route."""
    @wraps(f)
    @login_required
    def decorated_function(*args, **kwargs):
        if not current_user.is_student():
            flash('Access denied. Student account required.', 'danger')
            return redirect(url_for('faculty_dashboard'))
        return f(*args, **kwargs)
    return decorated_function


# -------------------------------------------------------------------
# Database Models
# -------------------------------------------------------------------
class User(db.Model, UserMixin):
    """
    User model for both Faculty and Students.
    Role is strictly 'faculty' or 'student'.
    """
    __tablename__ = 'user'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(200), nullable=False)
    role = db.Column(db.String(20), nullable=False)  # 'faculty' or 'student'
    created_at = db.Column(db.DateTime, default=utc_now)

    # Relationships
    courses = db.relationship('Course', backref='faculty', lazy=True, cascade='all, delete-orphan')
    enrollments = db.relationship('Enrollment', backref='student', lazy=True, cascade='all, delete-orphan')
    attendances = db.relationship('Attendance', backref='student', lazy=True, cascade='all, delete-orphan')

    def set_password(self, password):
        """Hashes the password using werkzeug security."""
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        """Verifies the hashed password."""
        return check_password_hash(self.password_hash, password)

    def is_faculty(self):
        return self.role == 'faculty'

    def is_student(self):
        return self.role == 'student'

    def __repr__(self):
        return f'<User {self.email} ({self.role})>'


class Course(db.Model):
    """
    Course created and managed by a faculty member.
    Course code must be unique (e.g. CS101, MATH201).
    """
    __tablename__ = 'course'

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(20), unique=True, nullable=False, index=True)
    name = db.Column(db.String(120), nullable=False)
    faculty_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=utc_now)

    # Relationships
    enrollments = db.relationship('Enrollment', backref='course', lazy=True, cascade='all, delete-orphan')
    sessions = db.relationship(
        'ClassSession',
        backref='course',
        lazy=True,
        cascade='all, delete-orphan',
        order_by='ClassSession.created_at.desc()'
    )

    def __repr__(self):
        return f'<Course {self.code}: {self.name}>'


class Enrollment(db.Model):
    """
    Associates a student with a course.
    Unique constraint on (student_id, course_id) prevents duplicate enrollment.
    """
    __tablename__ = 'enrollment'

    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    course_id = db.Column(db.Integer, db.ForeignKey('course.id'), nullable=False)
    enrolled_at = db.Column(db.DateTime, default=utc_now)

    __table_args__ = (
        db.UniqueConstraint('student_id', 'course_id', name='unique_student_course'),
    )

    def __repr__(self):
        return f'<Enrollment Student:{self.student_id} -> Course:{self.course_id}>'


class ClassSession(db.Model):
    """
    Represents an active or past attendance session for a class.
    Contains a cryptographically secure random token and expiration time.
    """
    __tablename__ = 'class_session'

    id = db.Column(db.Integer, primary_key=True)
    course_id = db.Column(db.Integer, db.ForeignKey('course.id'), nullable=False)
    token = db.Column(db.String(64), unique=True, nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=utc_now)
    expires_at = db.Column(db.DateTime, nullable=False)

    # Relationships
    attendances = db.relationship(
        'Attendance',
        backref='session',
        lazy=True,
        cascade='all, delete-orphan',
        order_by='Attendance.marked_at.desc()'
    )

    @property
    def is_expired(self):
        """Checks if the session validity window has elapsed."""
        return utc_now() > self.expires_at

    @property
    def seconds_remaining(self):
        """Remaining duration in seconds (returns 0 if expired)."""
        diff = (self.expires_at - utc_now()).total_seconds()
        return max(0, int(diff))

    def __repr__(self):
        return f'<ClassSession id={self.id} Course={self.course_id}>'


class Attendance(db.Model):
    """
    Records student attendance for a class session.
    Unique constraint on (session_id, student_id) guarantees no duplicate attendance.
    """
    __tablename__ = 'attendance'

    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey('class_session.id'), nullable=False)
    student_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    marked_at = db.Column(db.DateTime, default=utc_now)

    __table_args__ = (
        db.UniqueConstraint('session_id', 'student_id', name='unique_session_student'),
    )

    def __repr__(self):
        return f'<Attendance Session:{self.session_id} Student:{self.student_id}>'


@login_manager.user_loader
def load_user(user_id):
    """Flask-Login user loader callback using modern SQLAlchemy session.get."""
    return db.session.get(User, int(user_id))



# -------------------------------------------------------------------
# Authentication Routes
# -------------------------------------------------------------------
@app.route('/')
def index():
    """Landing page or direct redirect for authenticated users."""
    if current_user.is_authenticated:
        if current_user.is_faculty():
            return redirect(url_for('faculty_dashboard'))
        return redirect(url_for('student_dashboard'))
    return render_template('index.html')


@app.route('/register', methods=['GET', 'POST'])
def register():
    """User registration for both Students and Faculty."""
    if current_user.is_authenticated:
        return redirect(url_for('index'))

    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        role = request.form.get('role', 'student').strip().lower()

        # Validation
        if not name or not email or not password:
            flash('All fields are required.', 'danger')
            return render_template('register.html')

        if len(password) < 6:
            flash('Password must be at least 6 characters long.', 'danger')
            return render_template('register.html')

        if role not in ('student', 'faculty'):
            flash('Please select a valid role (Student or Faculty).', 'danger')
            return render_template('register.html')

        if User.query.filter_by(email=email).first():
            flash('An account with this email already exists. Please log in.', 'warning')
            return redirect(url_for('login'))

        # Create user
        new_user = User(name=name, email=email, role=role)
        new_user.set_password(password)
        db.session.add(new_user)
        db.session.commit()

        login_user(new_user)
        flash(f'Welcome, {new_user.name}! Account created successfully as {role.capitalize()}.', 'success')

        if role == 'faculty':
            return redirect(url_for('faculty_dashboard'))
        return redirect(url_for('student_dashboard'))

    return render_template('register.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    """User login with safe redirect to next URL."""
    if current_user.is_authenticated:
        return redirect(url_for('index'))

    next_page = request.args.get('next')

    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        submitted_next = request.form.get('next')

        user = User.query.filter_by(email=email).first()

        if user and user.check_password(password):
            login_user(user)
            flash(f'Logged in successfully as {user.name} ({user.role.capitalize()}).', 'success')

            # Validate next URL to prevent open-redirect attacks
            target = submitted_next or next_page
            if target and is_safe_url(target):
                return redirect(target)

            if user.is_faculty():
                return redirect(url_for('faculty_dashboard'))
            return redirect(url_for('student_dashboard'))
        else:
            flash('Invalid email or password. Please try again.', 'danger')

    return render_template('login.html', next=next_page)


@app.route('/logout')
@login_required
def logout():
    """Logs out the active user."""
    logout_user()
    flash('You have been logged out safely.', 'info')
    return redirect(url_for('index'))


# -------------------------------------------------------------------
# Faculty Routes
# -------------------------------------------------------------------
@app.route('/faculty/dashboard')
@faculty_required
def faculty_dashboard():
    """
    Faculty Dashboard:
    - Lists courses created by this faculty
    - Provides quick stats (enrolled students, total sessions)
    - Modal/form to create a new course
    """
    courses = Course.query.filter_by(faculty_id=current_user.id).order_by(Course.created_at.desc()).all()

    # Precompute summary counts for each course
    course_data = []
    for c in courses:
        enrolled_count = Enrollment.query.filter_by(course_id=c.id).count()
        session_count = ClassSession.query.filter_by(course_id=c.id).count()
        active_session = ClassSession.query.filter(
            ClassSession.course_id == c.id,
            ClassSession.expires_at > utc_now()
        ).first()

        course_data.append({
            'course': c,
            'enrolled_count': enrolled_count,
            'session_count': session_count,
            'active_session': active_session
        })

    return render_template('faculty_dashboard.html', course_data=course_data)


@app.route('/course/create', methods=['POST'])
@faculty_required
def create_course():
    """Creates a new course for the logged-in faculty."""
    code = request.form.get('code', '').strip().upper()
    name = request.form.get('name', '').strip()

    if not code or not name:
        flash('Both Course Code and Course Name are required.', 'danger')
        return redirect(url_for('faculty_dashboard'))

    # Check for existing code
    if Course.query.filter_by(code=code).first():
        flash(f'Course code "{code}" is already in use. Please use a unique code.', 'warning')
        return redirect(url_for('faculty_dashboard'))

    new_course = Course(code=code, name=name, faculty_id=current_user.id)
    db.session.add(new_course)
    db.session.commit()

    flash(f'Course "{code} - {name}" successfully created!', 'success')
    return redirect(url_for('faculty_dashboard'))


@app.route('/course/<int:course_id>/start-session', methods=['POST'])
@faculty_required
def start_session(course_id):
    """
    Starts a new class session with a random secret token and 5-minute expiry.
    Restricted to the course's owner.
    """
    course = Course.query.get_or_404(course_id)
    if course.faculty_id != current_user.id:
        abort(403)

    # Generate a cryptographically secure random token (URL-safe string)
    token = secrets.token_urlsafe(32)
    expires_at = utc_now() + timedelta(minutes=SESSION_EXPIRY_MINUTES)

    session = ClassSession(course_id=course.id, token=token, expires_at=expires_at)
    db.session.add(session)
    db.session.commit()

    flash(f'Attendance session for {course.code} started! The QR code is active for {SESSION_EXPIRY_MINUTES} minutes.', 'success')
    return redirect(url_for('session_view', session_id=session.id))


@app.route('/session/<int:session_id>')
@faculty_required
def session_view(session_id):
    """
    Session View:
    - Displays the generated QR Code image
    - Shows live countdown timer (JS)
    - Displays live attendees list
    - Shows network scan URL so faculty knows the exact URL phones will access
    """
    session = ClassSession.query.get_or_404(session_id)
    if session.course.faculty_id != current_user.id:
        abort(403)

    # Construct mobile-accessible QR scan URL
    host = request.host
    # If faculty opens on localhost or 127.0.0.1, replace host with LAN IP for phone scanners
    if host.startswith('localhost') or host.startswith('127.0.0.1'):
        lan_ip = get_lan_ip()
        scan_url = f"http://{lan_ip}:{SERVER_PORT}{url_for('mark_attendance', token=session.token)}"
    else:
        scan_url = request.host_url.rstrip('/') + url_for('mark_attendance', token=session.token)

    attendees = Attendance.query.filter_by(session_id=session.id).order_by(Attendance.marked_at.desc()).all()

    return render_template(
        'session_view.html',
        session=session,
        scan_url=scan_url,
        attendees=attendees,
        seconds_remaining=session.seconds_remaining,
        expiry_minutes=SESSION_EXPIRY_MINUTES
    )


@app.route('/qr-image/<token>')
def qr_image(token):
    """
    Dynamically generates and serves a QR Code image in PNG format.
    Encodes the URL to mark attendance.
    """
    session = ClassSession.query.filter_by(token=token).first_or_404()

    # Determine URL
    host = request.host
    if host.startswith('localhost') or host.startswith('127.0.0.1'):
        lan_ip = get_lan_ip()
        scan_url = f"http://{lan_ip}:{SERVER_PORT}{url_for('mark_attendance', token=session.token)}"
    else:
        scan_url = request.host_url.rstrip('/') + url_for('mark_attendance', token=session.token)

    # Generate QR Code using the qrcode library
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10,
        border=3,
    )
    qr.add_data(scan_url)
    qr.make(fit=True)

    img = qr.make_image(fill_color="#0f172a", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    buf.seek(0)

    return send_file(buf, mimetype='image/png')


@app.route('/api/session/<int:session_id>/status')
@faculty_required
def api_session_status(session_id):
    """
    JSON API endpoint polled by the session page.
    Returns current expiration status, seconds remaining, and list of attendees.
    """
    session = ClassSession.query.get_or_404(session_id)
    if session.course.faculty_id != current_user.id:
        abort(403)

    attendees = Attendance.query.filter_by(session_id=session.id).order_by(Attendance.marked_at.desc()).all()
    attendee_list = [
        {
            'name': att.student.name,
            'email': att.student.email,
            'marked_at': att.marked_at.strftime('%H:%M:%S')
        }
        for att in attendees
    ]

    return jsonify({
        'is_expired': session.is_expired,
        'seconds_remaining': session.seconds_remaining,
        'attendee_count': len(attendees),
        'attendees': attendee_list
    })


@app.route('/course/<int:course_id>/report')
@faculty_required
def course_report(course_id):
    """
    Faculty Attendance Report:
    - Lists all enrolled students with attended/total counts, percentage, and status
    - Highlights rows with attendance < 75%
    - Calculates course-wide attendance metrics and chart data
    """
    course = Course.query.get_or_404(course_id)
    if course.faculty_id != current_user.id:
        abort(403)

    # Total sessions conducted for this course
    total_sessions = ClassSession.query.filter_by(course_id=course.id).count()

    # Query all enrolled students
    enrollments = Enrollment.query.filter_by(course_id=course.id).all()

    student_reports = []
    low_attendance_count = 0
    total_percentage_sum = 0.0

    for enr in enrollments:
        student = enr.student
        attended_count = Attendance.query.join(ClassSession).filter(
            ClassSession.course_id == course.id,
            Attendance.student_id == student.id
        ).count()

        if total_sessions > 0:
            percentage = round((attended_count / total_sessions) * 100, 1)
        else:
            percentage = 100.0  # If no classes held yet, default clean 100%

        total_percentage_sum += percentage
        is_low = (percentage < ATTENDANCE_THRESHOLD) and (total_sessions > 0)
        if is_low:
            low_attendance_count += 1

        student_reports.append({
            'student': student,
            'enrolled_at': enr.enrolled_at,
            'attended': attended_count,
            'total': total_sessions,
            'percentage': percentage,
            'is_low': is_low,
            'status': 'At Risk' if is_low else 'Satisfactory'
        })

    # Sort student reports by percentage ascending so low attendance is immediately visible
    student_reports.sort(key=lambda x: (x['percentage'], x['student'].name))

    enrolled_count = len(enrollments)
    average_attendance = round(total_percentage_sum / enrolled_count, 1) if enrolled_count > 0 else 0.0

    # Recent sessions list for the course
    recent_sessions = ClassSession.query.filter_by(course_id=course.id).order_by(ClassSession.created_at.desc()).all()

    return render_template(
        'course_report.html',
        course=course,
        student_reports=student_reports,
        total_sessions=total_sessions,
        enrolled_count=enrolled_count,
        average_attendance=average_attendance,
        low_attendance_count=low_attendance_count,
        threshold=ATTENDANCE_THRESHOLD,
        recent_sessions=recent_sessions
    )


@app.route('/course/<int:course_id>/report/csv')
@faculty_required
def export_course_csv(course_id):
    """
    Bonus Feature:
    Exports course attendance report as a downloadable CSV spreadsheet.
    """
    course = Course.query.get_or_404(course_id)
    if course.faculty_id != current_user.id:
        abort(403)

    total_sessions = ClassSession.query.filter_by(course_id=course.id).count()
    enrollments = Enrollment.query.filter_by(course_id=course.id).all()

    output = io.StringIO()
    writer = csv.writer(output)

    # Write CSV Header
    writer.writerow(['Student ID', 'Student Name', 'Email', 'Attended Sessions', 'Total Sessions', 'Attendance %', 'Status'])

    for enr in enrollments:
        student = enr.student
        attended_count = Attendance.query.join(ClassSession).filter(
            ClassSession.course_id == course.id,
            Attendance.student_id == student.id
        ).count()
        percentage = round((attended_count / total_sessions) * 100, 1) if total_sessions > 0 else 100.0
        status = 'LOW ATTENDANCE' if (percentage < ATTENDANCE_THRESHOLD and total_sessions > 0) else 'SATISFACTORY'

        writer.writerow([
            student.id,
            student.name,
            student.email,
            attended_count,
            total_sessions,
            f"{percentage}%",
            status
        ])

    csv_data = output.getvalue()
    filename = f"attendance_report_{course.code}_{utc_now().strftime('%Y%m%d')}.csv"

    return Response(
        csv_data,
        mimetype='text/csv',
        headers={'Content-Disposition': f'attachment; filename={filename}'}
    )


@app.route('/course/<int:course_id>/send-alerts', methods=['POST'])
@faculty_required
def send_attendance_alerts(course_id):
    """
    Bonus Feature:
    Simulates sending email notifications to all students below the 75% threshold.
    """
    course = Course.query.get_or_404(course_id)
    if course.faculty_id != current_user.id:
        abort(403)

    total_sessions = ClassSession.query.filter_by(course_id=course.id).count()
    if total_sessions == 0:
        flash('No sessions have been conducted yet. No alerts sent.', 'info')
        return redirect(url_for('course_report', course_id=course.id))

    enrollments = Enrollment.query.filter_by(course_id=course.id).all()
    alerted_students = []

    for enr in enrollments:
        student = enr.student
        attended_count = Attendance.query.join(ClassSession).filter(
            ClassSession.course_id == course.id,
            Attendance.student_id == student.id
        ).count()
        percentage = round((attended_count / total_sessions) * 100, 1)
        if percentage < ATTENDANCE_THRESHOLD:
            # Here real email integration (e.g. Flask-Mail / SendGrid) could be hooked
            alerted_students.append(student.email)

    if alerted_students:
        flash(f'Attendance warning dispatched to {len(alerted_students)} student(s) below {ATTENDANCE_THRESHOLD}% threshold ({", ".join(alerted_students)}).', 'success')
    else:
        flash(f'Great news! All enrolled students have {ATTENDANCE_THRESHOLD}% or higher attendance.', 'success')

    return redirect(url_for('course_report', course_id=course.id))


# -------------------------------------------------------------------
# Student Routes
# -------------------------------------------------------------------
@app.route('/student/dashboard')
@student_required
def student_dashboard():
    """
    Student Dashboard:
    - Lists enrolled courses with attended/total classes and percentage
    - Displays progress bars colored dynamically (green >= 75%, red < 75%)
    - Shows red warning when attendance is below 75%
    - Input form to enroll in new courses using course code
    - Lists recent attendance marks
    """
    enrollments = Enrollment.query.filter_by(student_id=current_user.id).all()

    course_stats = []
    has_any_low_attendance = False

    for enr in enrollments:
        c = enr.course
        total_sessions = ClassSession.query.filter_by(course_id=c.id).count()
        attended_count = Attendance.query.join(ClassSession).filter(
            ClassSession.course_id == c.id,
            Attendance.student_id == current_user.id
        ).count()

        if total_sessions > 0:
            pct = round((attended_count / total_sessions) * 100, 1)
            is_low = pct < ATTENDANCE_THRESHOLD
        else:
            pct = 100.0
            is_low = False

        if is_low:
            has_any_low_attendance = True

        course_stats.append({
            'course': c,
            'faculty_name': c.faculty.name,
            'attended': attended_count,
            'total': total_sessions,
            'percentage': pct,
            'is_low': is_low
        })

    # Recent attendances across all courses
    recent_attendances = Attendance.query.filter_by(student_id=current_user.id)\
        .order_by(Attendance.marked_at.desc()).limit(10).all()

    return render_template(
        'student_dashboard.html',
        course_stats=course_stats,
        recent_attendances=recent_attendances,
        threshold=ATTENDANCE_THRESHOLD,
        has_any_low_attendance=has_any_low_attendance
    )


@app.route('/course/enroll', methods=['POST'])
@student_required
def enroll_course():
    """Enrolls the logged-in student into a course using its unique Course Code."""
    code = request.form.get('code', '').strip().upper()

    if not code:
        flash('Please enter a course code.', 'danger')
        return redirect(url_for('student_dashboard'))

    course = Course.query.filter_by(code=code).first()
    if not course:
        flash(f'Course with code "{code}" does not exist. Please check with your professor.', 'danger')
        return redirect(url_for('student_dashboard'))

    existing_enr = Enrollment.query.filter_by(student_id=current_user.id, course_id=course.id).first()
    if existing_enr:
        flash(f'You are already enrolled in {course.code} - {course.name}.', 'info')
        return redirect(url_for('student_dashboard'))

    enrollment = Enrollment(student_id=current_user.id, course_id=course.id)
    db.session.add(enrollment)
    db.session.commit()

    flash(f'Successfully enrolled in {course.code}: {course.name}!', 'success')
    return redirect(url_for('student_dashboard'))


# -------------------------------------------------------------------
# Attendance Marking Core Route (Scan Target)
# -------------------------------------------------------------------
@app.route('/mark/<token>')
def mark_attendance(token):
    """
    Mark Attendance Core Route:
    Target of the QR Code scanned by students.
    
    Verifies sequentially in strict order:
    1. User is authenticated (if logged out -> redirect to login with next=<this_url>)
    2. User is logged in as a student (rejects faculty)
    3. QR Session exists and has not expired (5-minute validity window)
    4. Student is enrolled in the course
    5. Attendance has not already been marked (duplicate check)
    
    Renders mark_attendance.html with distinct, clear success or error states.
    """
    # Check 1: User is authenticated
    if not current_user.is_authenticated:
        flash('Please log in with your student credentials to mark attendance.', 'warning')
        return redirect(url_for('login', next=request.path))

    # Check 2: User is a logged-in student
    if not current_user.is_student():
        return render_template(
            'mark_attendance.html',
            status='error',
            title='Role Mismatch',
            message='You are currently logged in with a Faculty account. Attendance can only be recorded by Student accounts. Please log out and sign in as a student.'
        )

    # Find the session by token
    session = ClassSession.query.filter_by(token=token).first()
    if not session:
        return render_template(
            'mark_attendance.html',
            status='error',
            title='Invalid QR Code',
            message='This attendance QR code does not exist or has been invalidated.'
        )

    # Check 3: QR has not expired
    if session.is_expired:
        return render_template(
            'mark_attendance.html',
            status='error',
            title='QR Code Expired',
            message=f'This attendance QR code expired at {session.expires_at.strftime("%H:%M:%S UTC")} ({SESSION_EXPIRY_MINUTES}-minute time limit reached). Please speak directly with your instructor.',
            course=session.course
        )

    # Check 4: Student is enrolled in the course
    enrollment = Enrollment.query.filter_by(
        student_id=current_user.id,
        course_id=session.course_id
    ).first()

    if not enrollment:
        return render_template(
            'mark_attendance.html',
            status='error',
            title='Not Enrolled In Course',
            message=f'You are not enrolled in {session.course.code} - {session.course.name}. You must first enroll in this course from your dashboard before attendance can be marked.',
            course=session.course,
            can_enroll=True
        )

    # Check 5: Attendance is not already marked
    existing_attendance = Attendance.query.filter_by(
        session_id=session.id,
        student_id=current_user.id
    ).first()

    if existing_attendance:
        return render_template(
            'mark_attendance.html',
            status='warning',
            title='Already Marked',
            message=f'Your attendance was already recorded at {existing_attendance.marked_at.strftime("%Y-%m-%d %H:%M:%S UTC")}. Duplicate attendance is strictly prohibited.',
            course=session.course,
            attendance=existing_attendance
        )

    # All checks passed: Record attendance safely
    new_attendance = Attendance(
        session_id=session.id,
        student_id=current_user.id,
        marked_at=utc_now()
    )
    db.session.add(new_attendance)
    db.session.commit()

    return render_template(
        'mark_attendance.html',
        status='success',
        title='Attendance Confirmed!',
        message=f'Your attendance for {session.course.code}: {session.course.name} has been successfully recorded.',
        course=session.course,
        attendance=new_attendance
    )


# -------------------------------------------------------------------
# Error Handlers
# -------------------------------------------------------------------
@app.errorhandler(403)
def forbidden(e):
    return render_template(
        'mark_attendance.html',
        status='error',
        title='403 Forbidden',
        message='You do not have permission to access this resource or course.'
    ), 403


@app.errorhandler(404)
def page_not_found(e):
    return render_template(
        'mark_attendance.html',
        status='error',
        title='404 Not Found',
        message='The requested page or resource could not be found.'
    ), 404


# -------------------------------------------------------------------
# Database Initialization & Main Runner
# -------------------------------------------------------------------
with app.app_context():
    db.create_all()

if __name__ == '__main__':
    lan_ip = get_lan_ip()
    print("=" * 65)
    print("  CAMPUS QR ATTENDANCE SYSTEM")
    print("=" * 65)
    print(f" * Localhost URL:      http://127.0.0.1:{SERVER_PORT}")
    print(f" * Mobile Wi-Fi URL:   http://{lan_ip}:{SERVER_PORT}")
    print(f" * Session Expiry:     {SESSION_EXPIRY_MINUTES} minutes")
    print(f" * Warning Threshold:  {ATTENDANCE_THRESHOLD}%")
    print("=" * 65)
    # Run listening on all interfaces (0.0.0.0) so devices on the same Wi-Fi can connect
    app.run(host='0.0.0.0', port=SERVER_PORT, debug=True)
