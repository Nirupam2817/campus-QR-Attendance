"""
Automated Test Suite for Campus QR Attendance System
===================================================
Tests all functional requirements, security constraints, and edge cases:
- Authentication & Safe Redirects
- Faculty & Student access controls (403 errors)
- Course creation & ClassSession generation
- QR code image generation
- Sequential attendance verification checks:
  1. Login check
  2. Student role check
  3. Session expiration check
  4. Course enrollment check
  5. Duplicate attendance prevention check
- CSV Export & Report metrics
"""

import unittest
from datetime import timedelta
import secrets

from app import app, db, User, Course, Enrollment, ClassSession, Attendance, utc_now

class CampusQRAttendanceTestCase(unittest.TestCase):
    def setUp(self):
        app.config['TESTING'] = True
        app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
        app.config['WTF_CSRF_ENABLED'] = False
        self.client = app.test_client()

        with app.app_context():
            db.create_all()

            # Create Faculty 1
            self.faculty = User(name="Prof. Alan Turing", email="turing@campus.edu", role="faculty")
            self.faculty.set_password("secure123")
            db.session.add(self.faculty)

            # Create Faculty 2 (to test 403 Forbidden access)
            self.other_faculty = User(name="Prof. Ada Lovelace", email="ada@campus.edu", role="faculty")
            self.other_faculty.set_password("secure123")
            db.session.add(self.other_faculty)

            # Create Students
            self.student1 = User(name="Grace Hopper", email="grace@campus.edu", role="student")
            self.student1.set_password("secure123")

            self.student2 = User(name="John von Neumann", email="john@campus.edu", role="student")
            self.student2.set_password("secure123")

            db.session.add_all([self.student1, self.student2])
            db.session.commit()

            # Create Course for Faculty 1
            self.course = Course(code="CS50", name="Intro to Computer Science", faculty_id=self.faculty.id)
            db.session.add(self.course)
            db.session.commit()

            # Enroll Student 1 in CS50
            self.enrollment = Enrollment(student_id=self.student1.id, course_id=self.course.id)
            db.session.add(self.enrollment)
            db.session.commit()

            self.faculty_id = self.faculty.id
            self.other_faculty_id = self.other_faculty.id
            self.student1_id = self.student1.id
            self.student2_id = self.student2.id
            self.course_id = self.course.id

    def tearDown(self):
        with app.app_context():
            db.session.remove()
            db.drop_all()

    def login(self, email, password):
        return self.client.post('/login', data={'email': email, 'password': password}, follow_redirects=True)

    def logout(self):
        return self.client.get('/logout', follow_redirects=True)

    def test_registration_and_login(self):
        """Test user registration and subsequent login."""
        res = self.client.post('/register', data={
            'name': 'Test Student',
            'email': 'newstudent@campus.edu',
            'password': 'password123',
            'role': 'student'
        }, follow_redirects=True)
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'Student Dashboard', res.data)

    def test_open_redirect_protection(self):
        """Ensures malicious external URLs in next parameter are rejected."""
        res = self.client.post('/login?next=https://evil.com', data={
            'email': 'grace@campus.edu',
            'password': 'secure123'
        }, follow_redirects=False)
        self.assertNotEqual(res.headers.get('Location'), 'https://evil.com')

    def test_faculty_course_creation_and_session(self):
        """Test creating a course and starting a 5-minute session."""
        self.login('turing@campus.edu', 'secure123')
        
        # Create course
        res = self.client.post('/course/create', data={
            'code': 'CS200',
            'name': 'Computer Architecture'
        }, follow_redirects=True)
        self.assertIn(b'CS200', res.data)

        # Start session
        res = self.client.post(f'/course/{self.course_id}/start-session', follow_redirects=True)
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'Live Attendance Log', res.data)
        self.assertIn(b'Time Remaining to Scan', res.data)

    def test_faculty_permission_isolation(self):
        """Faculty cannot access or start sessions for another faculty member's course."""
        self.login('ada@campus.edu', 'secure123')
        # Attempt to access Course 1 (owned by Turing)
        res = self.client.get(f'/course/{self.course_id}/report')
        self.assertEqual(res.status_code, 403)

    def test_qr_code_image_endpoint(self):
        """Verify QR image generation endpoint returns a valid PNG."""
        with app.app_context():
            session = ClassSession(
                course_id=self.course_id,
                token=secrets.token_urlsafe(32),
                expires_at=utc_now() + timedelta(minutes=5)
            )
            db.session.add(session)
            db.session.commit()
            token = session.token

        res = self.client.get(f'/qr-image/{token}')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.content_type, 'image/png')
        self.assertTrue(len(res.data) > 100)

    def test_attendance_marking_sequential_checks(self):
        """Comprehensive verification of all 5 attendance checks."""
        with app.app_context():
            # Active session
            active_session = ClassSession(
                course_id=self.course_id,
                token='active-test-token-123',
                expires_at=utc_now() + timedelta(minutes=5)
            )
            # Expired session
            expired_session = ClassSession(
                course_id=self.course_id,
                token='expired-test-token-123',
                expires_at=utc_now() - timedelta(minutes=1)
            )
            db.session.add_all([active_session, expired_session])
            db.session.commit()

        # Check 1: User is logged out -> redirected to login with next
        res = self.client.get('/mark/active-test-token-123', follow_redirects=True)
        self.assertIn(b'Sign In', res.data)
        self.assertIn(b'Please log in with your student credentials', res.data)

        # Check 2: User is logged in as Faculty -> Role Mismatch error
        self.login('turing@campus.edu', 'secure123')
        res = self.client.get('/mark/active-test-token-123', follow_redirects=True)
        self.assertIn(b'Role Mismatch', res.data)
        self.logout()

        # Check 3: QR Code Expired
        self.login('grace@campus.edu', 'secure123')
        res = self.client.get('/mark/expired-test-token-123', follow_redirects=True)
        self.assertIn(b'QR Code Expired', res.data)

        # Check 4: Student is not enrolled in the course
        self.logout()
        self.login('john@campus.edu', 'secure123') # John is not enrolled in CS50
        res = self.client.get('/mark/active-test-token-123', follow_redirects=True)
        self.assertIn(b'Not Enrolled In Course', res.data)
        self.logout()

        # Check 5: Successful attendance mark for enrolled student (Grace)
        self.login('grace@campus.edu', 'secure123')
        res = self.client.get('/mark/active-test-token-123', follow_redirects=True)
        self.assertIn(b'Attendance Confirmed!', res.data)

        # Check 6: Duplicate attendance attempt -> Rejected!
        res2 = self.client.get('/mark/active-test-token-123', follow_redirects=True)
        self.assertIn(b'Already Marked', res2.data)
        self.assertIn(b'Duplicate attendance is strictly prohibited', res2.data)

    def test_student_enrollment_via_course_code(self):
        """Verify student can enroll using Course Code from their dashboard."""
        self.login('john@campus.edu', 'secure123')
        res = self.client.post('/course/enroll', data={'code': 'CS50'}, follow_redirects=True)
        self.assertIn(b'Successfully enrolled in CS50', res.data)

    def test_course_csv_export(self):
        """Verify CSV report download contains expected headers and data."""
        self.login('turing@campus.edu', 'secure123')
        res = self.client.get(f'/course/{self.course_id}/report/csv')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.content_type, 'text/csv; charset=utf-8')
        self.assertIn(b'Student ID,Student Name,Email', res.data)
        self.assertIn(b'Grace Hopper', res.data)

if __name__ == '__main__':
    unittest.main()
