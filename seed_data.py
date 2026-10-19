"""
Seed Script for Campus QR Attendance System
===========================================
Populates the database with realistic sample data:
- 1 Faculty account (Prof. Robert Miller)
- 4 Student accounts (Alice, Bob, Charlie, Diana)
- 2 Courses (CS101, CS202)
- Enrollments and past class sessions to demonstrate attendance percentage
  calculations, including students with both good (>=75%) and low (<75%) attendance.
"""

from datetime import timedelta
from app import app, db, User, Course, Enrollment, ClassSession, Attendance, utc_now
import secrets

def seed():
    with app.app_context():
        # Clean existing tables
        print("Resetting database tables...")
        db.drop_all()
        db.create_all()

        print("Creating Faculty and Student users...")
        # 1. Create Faculty
        faculty = User(
            name="Prof. Robert Miller",
            email="faculty@campus.edu",
            role="faculty"
        )
        faculty.set_password("password123")
        db.session.add(faculty)

        # 2. Create Students
        students_data = [
            ("Alice Johnson", "alice@campus.edu"),
            ("Bob Smith", "bob@campus.edu"),
            ("Charlie Davis", "charlie@campus.edu"),
            ("Diana Prince", "diana@campus.edu"),
        ]

        students = []
        for name, email in students_data:
            s = User(name=name, email=email, role="student")
            s.set_password("password123")
            db.session.add(s)
            students.append(s)

        db.session.commit()

        print("Creating Courses...")
        # 3. Create Courses
        course_cs101 = Course(
            code="CS101",
            name="Data Structures & Algorithms",
            faculty_id=faculty.id
        )
        course_cs202 = Course(
            code="CS202",
            name="Database Management Systems",
            faculty_id=faculty.id
        )
        db.session.add_all([course_cs101, course_cs202])
        db.session.commit()

        print("Enrolling Students in Courses...")
        # 4. Enroll Students
        # All 4 enrolled in CS101
        for s in students:
            db.session.add(Enrollment(student_id=s.id, course_id=course_cs101.id))

        # Alice & Bob enrolled in CS202
        db.session.add(Enrollment(student_id=students[0].id, course_id=course_cs202.id))
        db.session.add(Enrollment(student_id=students[1].id, course_id=course_cs202.id))
        db.session.commit()

        print("Creating past class sessions and attendance records for CS101...")
        # 5. Create 4 past sessions for CS101
        # Alice attended 4/4 (100% - Green)
        # Bob attended 3/4 (75% - Green)
        # Charlie attended 2/4 (50% - Red Warning)
        # Diana attended 1/4 (25% - Red Warning)
        
        now = utc_now()
        for i in range(4):
            session_time = now - timedelta(days=(4 - i))
            session = ClassSession(
                course_id=course_cs101.id,
                token=secrets.token_urlsafe(32),
                created_at=session_time,
                expires_at=session_time + timedelta(minutes=5)
            )
            db.session.add(session)
            db.session.flush()

            # Alice attends all 4 sessions
            db.session.add(Attendance(session_id=session.id, student_id=students[0].id, marked_at=session_time + timedelta(seconds=45)))

            # Bob attends sessions 0, 1, 2 (3/4)
            if i in (0, 1, 2):
                db.session.add(Attendance(session_id=session.id, student_id=students[1].id, marked_at=session_time + timedelta(seconds=60)))

            # Charlie attends sessions 0, 1 (2/4)
            if i in (0, 1):
                db.session.add(Attendance(session_id=session.id, student_id=students[2].id, marked_at=session_time + timedelta(seconds=75)))

            # Diana attends session 0 only (1/4)
            if i == 0:
                db.session.add(Attendance(session_id=session.id, student_id=students[3].id, marked_at=session_time + timedelta(seconds=90)))

        db.session.commit()

        print("\n" + "=" * 55)
        print("Database seeded successfully!")
        print("=" * 55)
        print("Faculty Account:")
        print("  Email:    faculty@campus.edu")
        print("  Password: password123")
        print("\nStudent Accounts (all passwords: password123):")
        print("  1. alice@campus.edu   (CS101: 100% Attendance)")
        print("  2. bob@campus.edu     (CS101: 75% Attendance)")
        print("  3. charlie@campus.edu (CS101: 50% - Low Attendance Alert)")
        print("  4. diana@campus.edu   (CS101: 25% - Low Attendance Alert)")
        print("=" * 55)

if __name__ == '__main__':
    seed()
