# Campus QR Attendance System

A modern, anti-proxy, web-based classroom attendance system built with **Python**, **Flask**, **SQLite**, and **Bootstrap 5**.

---

## Key Features

1. **Role-Based Access Control**:
   - **Faculty**: Create courses, launch time-bounded QR sessions, track attendees in real-time, view reports, download CSV spreadsheets, and send alert warnings.
   - **Student**: Enroll in courses using unique course codes, scan classroom QR codes, view personal attendance percentages, and receive alerts if below 75%.
2. **Dynamic 5-Minute QR Code Sessions**:
   - Each session generates a cryptographically random token (`secrets.token_urlsafe(32)`) valid for exactly 5 minutes (configurable).
   - Generates PNG QR images on the fly using `qrcode` and `Pillow`.
3. **Sequential 5-Step Security Verification**:
   - Step 1: User is an authenticated student.
   - Step 2: Role is verified (faculty accounts cannot mark attendance).
   - Step 3: QR session has not expired.
   - Step 4: Student is actively enrolled in the course.
   - Step 5: Duplicate check via SQLite unique database constraint (`session_id`, `student_id`).
4. **Live Polling & Countdown Timer**:
   - Faculty projection screen updates attendee logs every 3 seconds without refreshing.
   - Live JavaScript countdown timer turns red in the final minute and greys out upon expiration.
5. **Mobile & Network Friendly**:
   - Binds to `0.0.0.0` and auto-resolves local LAN IP so smartphones on the same Wi-Fi can scan without "localhost" connection issues.
6. **Analytics & Alerts**:
   - Visual progress bars with red highlights for attendance < 75%.
   - Chart.js breakdown of satisfactory vs. at-risk students.
   - One-click CSV export of course roster.

---

## Directory Structure

```text
campus_qr_attendance/
│
├── app.py                      # Main Flask application & routes
├── requirements.txt            # Python dependencies
├── seed_data.py                # Database seeder with sample accounts
├── test_attendance_system.py   # Automated unit and integration test suite
├── attendance.db               # SQLite database file (auto-created)
├── README.md                   # Documentation and run instructions
│
├── static/
│   └── css/
│       └── style.css           # Custom responsive styles & animations
│
└── templates/
    ├── base.html               # Master layout with navbar and alerts
    ├── index.html              # Public landing page with role guide
    ├── login.html              # Sign-in page with open-redirect protection
    ├── register.html           # User registration (Student / Faculty)
    ├── faculty_dashboard.html  # Faculty course management & start session
    ├── session_view.html       # Live QR projection screen & countdown
    ├── course_report.html      # Course analytics, CSV export, & student roster
    ├── student_dashboard.html  # Student attendance bars & course enrollment
    └── mark_attendance.html    # Mobile scan feedback (Success/Error/Warning)
```

---

## Quick Start & Installation

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. (Optional) Populate Sample Demo Data
```bash
python seed_data.py
```
This sets up sample faculty (`faculty@campus.edu`) and 4 students (`alice@campus.edu`, `bob@campus.edu`, etc.). All demo passwords are `password123`.

### 3. Run the Server
```bash
python app.py
```
By default, the server listens on `0.0.0.0:5000`.

---

## Testing with a Mobile Phone on Wi-Fi

1. **Connect to Same Wi-Fi**: Make sure your computer running Flask and your mobile phone are connected to the same Wi-Fi or hotspot.
2. **Find Your Local IP**:
   - When `python app.py` starts, it prints your Wi-Fi URL:
     ```text
     * Localhost URL:      http://127.0.0.1:5000
     * Mobile Wi-Fi URL:   http://192.168.1.15:5000
     ```
3. **Faculty Workflow**:
   - Open `http://localhost:5000` on your computer.
   - Log in as Faculty (`faculty@campus.edu` / `password123`).
   - Click **"Start Class Session"** for `CS101`.
   - The projector screen displays the QR Code and countdown timer.
4. **Student Workflow**:
   - Open your mobile phone camera or QR scanner app.
   - Point the camera at the QR code on your computer screen.
   - Tap the link. If logged out, log in with `alice@campus.edu` (`password123`).
   - The system displays a green **"Attendance Confirmed!"** screen.
   - Scan again to test the anti-duplicate warning: **"Already Marked"**.
   - Watch your computer screen update in real time with the new attendee!

> **Testing on a single laptop?**
> You can also click the **"Copy Link"** button on the faculty session screen, open an Incognito browser window, log in as a student, and paste the URL to test the exact same flow!
