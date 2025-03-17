from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, send_file, Response
import mysql.connector
from mysql.connector import Error
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import LoginManager, login_user, login_required, logout_user, UserMixin, current_user
import os
from werkzeug.utils import secure_filename
from datetime import datetime, timedelta
import csv
import io
import base64

app = Flask(__name__)
app.secret_key = 'your_secret_key'

# Configure upload folder
UPLOAD_FOLDER = 'static/profile_pictures'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# Ensure upload folder exists
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# Set up the login manager
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"

# Connect to the database
def get_db_connection():
    connection = mysql.connector.connect(
        host='localhost',
        user='root',
        password='',  # Your XAMPP MySQL password
        database='sitin'
    )
    return connection

# User class to handle user sessions
class User(UserMixin):
    def __init__(self, id, email, user_type, course, level, firstname=None, lastname=None, profile_picture=None, profile_picture_blob=None):
        self.id = id
        self.email = email
        self.user_type = user_type
        self.course = course
        self.level = level
        self.firstname = firstname
        self.lastname = lastname
        self.profile_picture = profile_picture or 'default_profile.jpg'
        self.profile_picture_blob = profile_picture_blob
        self.session = None  # Initialize session attribute


@login_manager.user_loader
def load_user(user_id):
    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)
    
    # Check if PROFILE_PICTURE_BLOB column exists
    cursor.execute("SHOW COLUMNS FROM users LIKE 'PROFILE_PICTURE_BLOB'")
    blob_column_exists = cursor.fetchone() is not None
    
    cursor.execute("SELECT * FROM USERS WHERE IDNO = %s", (user_id,))
    user_data = cursor.fetchone()
    connection.close()
    
    if user_data:
        # Convert BLOB to base64 string if it exists
        profile_picture_blob = None
        if blob_column_exists and 'PROFILE_PICTURE_BLOB' in user_data and user_data['PROFILE_PICTURE_BLOB']:
            profile_picture_blob = base64.b64encode(user_data['PROFILE_PICTURE_BLOB']).decode('utf-8')
            
        return User(
            id=user_data['IDNO'], 
            email=user_data['EMAIL'], 
            user_type=user_data['USER_TYPE'],
            course=user_data['COURSE'],
            level=user_data['LEVEL'],
            firstname=user_data['FIRSTNAME'],
            lastname=user_data['LASTNAME'],
            profile_picture=user_data.get('PROFILE_PICTURE', 'default_profile.jpg'),
            profile_picture_blob=profile_picture_blob
        )
    return None


# Registration Route
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        idno = request.form['idno']
        lastname = request.form['lastname']
        middlename = request.form['middlename']
        firstname = request.form['firstname']
        course = request.form['course']
        level = request.form['level']
        email = request.form['email']
        password = request.form['password']
        confirm_password = request.form['confirm_password']

        # Handle profile picture upload
        profile_picture = 'default_profile.jpg'  # Default image
        profile_picture_blob = None
        
        if 'profile_picture' in request.files:
            file = request.files['profile_picture']
            if file and allowed_file(file.filename):
                # Create unique filename using timestamp
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                filename = secure_filename(f"{timestamp}_{file.filename}")
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                profile_picture = filename
                
                # Also store as BLOB
                file.seek(0)  # Reset file pointer to beginning
                profile_picture_blob = file.read()

        if password != confirm_password:
            flash("Passwords do not match.", "danger")
            return redirect(url_for('register'))

        if len(middlename) != 1 or not middlename.isupper():
            flash("Middle name must be a single uppercase letter.", "danger")
            return redirect(url_for('register'))

        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)

        cursor.execute("SELECT * FROM users WHERE idno = %s", (idno,))
        if cursor.fetchone():
            flash("This ID number is already registered.", "danger")
            return redirect(url_for('register'))

        cursor.execute("SELECT * FROM users WHERE email = %s", (email,))
        if cursor.fetchone():
            flash("This email is already registered.", "danger")
            return redirect(url_for('register'))

        hashed_password = generate_password_hash(password)

        try:
            # Check if PROFILE_PICTURE_BLOB column exists
            cursor.execute("SHOW COLUMNS FROM users LIKE 'PROFILE_PICTURE_BLOB'")
            blob_column_exists = cursor.fetchone() is not None
            
            if blob_column_exists:
                query = """
                    INSERT INTO users (idno, lastname, middlename, firstname, course, level, email, password, user_type, PROFILE_PICTURE, PROFILE_PICTURE_BLOB)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'STUDENT', %s, %s)
                """
                cursor.execute(query, (idno, lastname, middlename, firstname, course, level, email, hashed_password, profile_picture, profile_picture_blob))
            else:
                # If BLOB column doesn't exist, add it first
                cursor.execute("ALTER TABLE users ADD COLUMN PROFILE_PICTURE_BLOB LONGBLOB")
                
                query = """
                    INSERT INTO users (idno, lastname, middlename, firstname, course, level, email, password, user_type, PROFILE_PICTURE, PROFILE_PICTURE_BLOB)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'STUDENT', %s, %s)
                """
                cursor.execute(query, (idno, lastname, middlename, firstname, course, level, email, hashed_password, profile_picture, profile_picture_blob))
                
            connection.commit()
            flash("Registration successful!", "success")
            return redirect(url_for('login'))
        except Exception as e:
            flash("An error occurred: " + str(e), "danger")
        finally:
            connection.close()

    return render_template('register.html')

# Login Route
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        idno = request.form['idno']
        password = request.form['password']
        role = request.form.get('role', 'student')  # Get the selected role

        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)
        
        # Check if PROFILE_PICTURE_BLOB column exists
        cursor.execute("SHOW COLUMNS FROM users LIKE 'PROFILE_PICTURE_BLOB'")
        blob_column_exists = cursor.fetchone() is not None
        
        # Modify query based on role
        if role == 'admin':
            cursor.execute("SELECT * FROM USERS WHERE IDNO = %s AND USER_TYPE = 'STAFF'", (idno,))
        else:
            cursor.execute("SELECT * FROM USERS WHERE IDNO = %s AND USER_TYPE = 'STUDENT'", (idno,))
            
        user_data = cursor.fetchone()
        connection.close()

        if user_data and check_password_hash(user_data['PASSWORD'], password):
            # Convert BLOB to base64 string if it exists
            profile_picture_blob = None
            if blob_column_exists and 'PROFILE_PICTURE_BLOB' in user_data and user_data['PROFILE_PICTURE_BLOB']:
                profile_picture_blob = base64.b64encode(user_data['PROFILE_PICTURE_BLOB']).decode('utf-8')
                
            # Ensure all required fields are passed to the User class
            user = User(
                id=user_data['IDNO'], 
                email=user_data['EMAIL'], 
                user_type=user_data['USER_TYPE'],
                course=user_data['COURSE'],
                level=user_data['LEVEL'],
                firstname=user_data['FIRSTNAME'],
                lastname=user_data['LASTNAME'],
                profile_picture=user_data.get('PROFILE_PICTURE', 'default_profile.jpg'),
                profile_picture_blob=profile_picture_blob
            )
            login_user(user)
            if user.user_type == 'STAFF':
                return redirect(url_for('admin_dashboard'))
            else:
                return redirect(url_for('student_dashboard'))
        else:
            if role == 'admin':
                flash('Invalid admin credentials.', 'danger')
            else:
                flash('Invalid student credentials.', 'danger')
            return redirect(url_for('login'))

    return render_template('login.html')


# Admin Dashboard
@app.route('/admin_dashboard')
@login_required
def admin_dashboard():
    if current_user.user_type != 'STAFF':
        return redirect(url_for('login'))
    return render_template('admin_dashboard.html')

# Student Dashboard
@app.route('/student_dashboard')
@login_required
def student_dashboard():
    if current_user.user_type != 'STUDENT':
        return redirect(url_for('login'))   
    return render_template('student_dashboard.html')

@app.route('/edit_info', methods=['POST'])
@login_required
def edit_info():
    firstname = request.form.get('firstname', current_user.firstname)
    lastname = request.form.get('lastname', current_user.lastname)
    email = request.form.get('email', current_user.email)
    course = request.form.get('course', current_user.course)
    level = request.form.get('level', current_user.level)
    password = request.form.get('password', '')

    connection = get_db_connection()
    cursor = connection.cursor()

    # Check if PROFILE_PICTURE_BLOB column exists
    cursor.execute("SHOW COLUMNS FROM users LIKE 'PROFILE_PICTURE_BLOB'")
    blob_column_exists = cursor.fetchone() is not None
    
    if not blob_column_exists:
        # Add the PROFILE_PICTURE_BLOB column if it doesn't exist
        try:
            cursor.execute("ALTER TABLE users ADD COLUMN PROFILE_PICTURE_BLOB LONGBLOB")
            connection.commit()
            blob_column_exists = True
        except Exception as e:
            flash(f"Error adding PROFILE_PICTURE_BLOB column: {str(e)}", "danger")
            connection.close()
            return redirect(url_for('student_dashboard'))

    # Handle profile picture update
    profile_picture_blob = None
    if 'profile_picture' in request.files:
        file = request.files['profile_picture']
        if file and file.filename:
            if allowed_file(file.filename):
                # Create unique filename using timestamp
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                filename = secure_filename(f"{timestamp}_{file.filename}")
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                
                # Store as BLOB
                file.seek(0)  # Reset file pointer to beginning
                profile_picture_blob = file.read()
                
                # Update profile picture filename and BLOB
                if blob_column_exists:
                    if password:
                        cursor.execute("""
                            UPDATE users
                            SET firstname = %s, lastname = %s, email = %s, course = %s, level = %s, 
                            password = %s, PROFILE_PICTURE = %s, PROFILE_PICTURE_BLOB = %s
                            WHERE idno = %s
                        """, (firstname, lastname, email, course, level, generate_password_hash(password), 
                              filename, profile_picture_blob, current_user.id))
                    else:
                        cursor.execute("""
                            UPDATE users
                            SET firstname = %s, lastname = %s, email = %s, course = %s, level = %s, 
                            PROFILE_PICTURE = %s, PROFILE_PICTURE_BLOB = %s
                            WHERE idno = %s
                        """, (firstname, lastname, email, course, level, filename, 
                              profile_picture_blob, current_user.id))
                else:
                    # If BLOB column doesn't exist for some reason, just update the filename
                    if password:
                        cursor.execute("""
                            UPDATE users
                            SET firstname = %s, lastname = %s, email = %s, course = %s, level = %s, 
                            password = %s, PROFILE_PICTURE = %s
                            WHERE idno = %s
                        """, (firstname, lastname, email, course, level, generate_password_hash(password), 
                              filename, current_user.id))
                    else:
                        cursor.execute("""
                            UPDATE users
                            SET firstname = %s, lastname = %s, email = %s, course = %s, level = %s, 
                            PROFILE_PICTURE = %s
                            WHERE idno = %s
                        """, (firstname, lastname, email, course, level, filename, current_user.id))
            else:
                flash('Invalid file type. Please upload a valid image file.', 'danger')
                connection.close()
                return redirect(url_for('student_dashboard'))
        else:
            # No new profile picture uploaded, just update other info
            if password:
                cursor.execute("""
                    UPDATE users
                    SET firstname = %s, lastname = %s, email = %s, course = %s, level = %s, password = %s
                    WHERE idno = %s
                """, (firstname, lastname, email, course, level, generate_password_hash(password), current_user.id))
            else:
                cursor.execute("""
                    UPDATE users
                    SET firstname = %s, lastname = %s, email = %s, course = %s, level = %s
                    WHERE idno = %s
                """, (firstname, lastname, email, course, level, current_user.id))
    else:
        # No profile picture field in form, just update other info
        if password:
            cursor.execute("""
                UPDATE users
                SET firstname = %s, lastname = %s, email = %s, course = %s, level = %s, password = %s
                WHERE idno = %s
            """, (firstname, lastname, email, course, level, generate_password_hash(password), current_user.id))
        else:
            cursor.execute("""
                UPDATE users
                SET firstname = %s, lastname = %s, email = %s, course = %s, level = %s
                WHERE idno = %s
            """, (firstname, lastname, email, course, level, current_user.id))

    connection.commit()
    connection.close()

    flash('Information updated successfully.', 'success')
    return redirect(url_for('student_dashboard'))

# Make Reservation Route
@app.route('/make_reservation', methods=['POST'])
@login_required
def make_reservation():
    session = request.form['session']

    connection = get_db_connection()
    cursor = connection.cursor()
    cursor.execute("""
        INSERT INTO reservations (user_id, session)
        VALUES (%s, %s)
    """, (current_user.id, session))
    connection.commit()
    connection.close()

    flash('Reservation made successfully.', 'success')
    return redirect(url_for('student_dashboard'))

# Logout Route
@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out.', 'info')
    return redirect(url_for('login'))

# Search Student Route
@app.route('/search_student/<student_id>')
@login_required
def search_student(student_id):
    if current_user.user_type != 'STAFF':
        return jsonify({'success': False, 'message': 'Unauthorized'}), 403

    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)
    
    # Check if PROFILE_PICTURE_BLOB column exists
    cursor.execute("SHOW COLUMNS FROM users LIKE 'PROFILE_PICTURE_BLOB'")
    blob_column_exists = cursor.fetchone() is not None
    
    cursor.execute("SELECT * FROM users WHERE idno = %s AND user_type = 'STUDENT'", (student_id,))
    student = cursor.fetchone()
    connection.close()

    if student:
        # Convert BLOB to base64 string if it exists
        profile_picture_blob = None
        if blob_column_exists and 'PROFILE_PICTURE_BLOB' in student and student['PROFILE_PICTURE_BLOB']:
            profile_picture_blob = base64.b64encode(student['PROFILE_PICTURE_BLOB']).decode('utf-8')
            
        return jsonify({
            'success': True,
            'student': {
                'id': student['IDNO'],
                'firstname': student['FIRSTNAME'],
                'middlename': student.get('MIDDLENAME', ''),
                'lastname': student['LASTNAME'],
                'email': student['EMAIL'],
                'course': student['COURSE'],
                'level': student['LEVEL'],
                'profile_picture': student.get('PROFILE_PICTURE', 'default_profile.jpg'),
                'profile_picture_blob': profile_picture_blob
            }
        })
    return jsonify({'success': False, 'message': 'Student not found'})

# Start Sit-in Session Route
@app.route('/start_sitin', methods=['POST'])
@login_required
def start_sitin():
    if current_user.user_type != 'STAFF':
        return jsonify({'success': False, 'message': 'Unauthorized'}), 403

    data = request.json
    student_id = data.get('student_id')
    pc_number = data.get('pc_number')
    time_limit = data.get('time_limit')
    purpose = data.get('purpose')
    lab = data.get('lab')

    if not all([student_id, pc_number, time_limit, purpose, lab]):
        return jsonify({'success': False, 'message': 'Missing required fields'}), 400

    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)

    # Check if student is already in an active session
    cursor.execute("SELECT * FROM sitin_sessions WHERE student_id = %s AND end_time IS NULL", (student_id,))
    if cursor.fetchone():
        connection.close()
        return jsonify({'success': False, 'message': 'Student already has an active session'})

    # Check if PC is already in use
    cursor.execute("SELECT * FROM sitin_sessions WHERE pc_number = %s AND end_time IS NULL", (pc_number,))
    if cursor.fetchone():
        connection.close()
        return jsonify({'success': False, 'message': 'PC is already in use'})

    try:
        # Start new sit-in session
        cursor.execute("""
            INSERT INTO sitin_sessions (student_id, pc_number, start_time, time_limit, purpose, lab)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (student_id, pc_number, datetime.now(), time_limit, purpose, lab))
        connection.commit()
        connection.close()
        return jsonify({'success': True})
    except Error as e:
        connection.close()
        return jsonify({'success': False, 'message': str(e)})

# End Sit-in Session Route
@app.route('/end_sitin', methods=['POST'])
@login_required
def end_sitin():
    if current_user.user_type != 'STAFF':
        return jsonify({'success': False, 'message': 'Unauthorized'}), 403

    data = request.json
    student_id = data.get('student_id')

    connection = get_db_connection()
    cursor = connection.cursor()

    try:
        # End the sit-in session
        cursor.execute("""
            UPDATE sitin_sessions 
            SET end_time = %s 
            WHERE student_id = %s AND end_time IS NULL
        """, (datetime.now(), student_id))
        connection.commit()
        connection.close()
        return jsonify({'success': True})
    except Error as e:
        connection.close()
        return jsonify({'success': False, 'message': str(e)})

# Get Active Sit-ins Route
@app.route('/get_active_sitins')
@login_required
def get_active_sitins():
    if current_user.user_type != 'STAFF':
        return jsonify({'success': False, 'message': 'Unauthorized'}), 403

    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)

    cursor.execute("""
        SELECT s.*, u.FIRSTNAME, u.LASTNAME 
        FROM sitin_sessions s
        JOIN users u ON s.student_id = u.IDNO
        WHERE s.end_time IS NULL
        ORDER BY s.start_time DESC
    """)
    
    sitins = cursor.fetchall()
    connection.close()

    return jsonify({
        'success': True,
        'sitins': [{
            'student_id': sitin['student_id'],
            'student_name': f"{sitin['FIRSTNAME']} {sitin['LASTNAME']}",
            'pc_number': sitin['pc_number'],
            'start_time': sitin['start_time'].strftime('%Y-%m-%d %H:%M:%S'),
            'time_limit': sitin['time_limit'],
            'purpose': sitin.get('purpose', 'N/A'),
            'lab': sitin.get('lab', 'N/A'),
            'elapsed_time': str(datetime.now() - sitin['start_time']).split('.')[0]  # Format as HH:MM:SS
        } for sitin in sitins]
    })

# Get Sit-in Records Route
@app.route('/get_sitin_records')
@login_required
def get_sitin_records():
    if current_user.user_type != 'STAFF':
        return jsonify({'success': False, 'message': 'Unauthorized'}), 403

    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)

    # Get today's records
    today = datetime.now().date()
    cursor.execute("""
        SELECT s.*, u.FIRSTNAME, u.LASTNAME 
        FROM sitin_sessions s
        JOIN users u ON s.student_id = u.IDNO
        WHERE DATE(s.start_time) = %s AND s.end_time IS NOT NULL
        ORDER BY s.start_time DESC
    """, (today,))
    
    records = cursor.fetchall()
    connection.close()

    return jsonify({
        'success': True,
        'records': [{
            'student_id': record['student_id'],
            'student_name': f"{record['FIRSTNAME']} {record['LASTNAME']}",
            'pc_number': record['pc_number'],
            'purpose': record.get('purpose', 'N/A'),
            'lab': record.get('lab', 'N/A'),
            'start_time': record['start_time'].strftime('%Y-%m-%d %H:%M:%S'),
            'end_time': record['end_time'].strftime('%Y-%m-%d %H:%M:%S'),
            'duration': str(record['end_time'] - record['start_time']).split('.')[0]  # Format as HH:MM:SS
        } for record in records]
    })

# Export Data Route
@app.route('/export_data/<format>', methods=['GET'])
@login_required
def export_data(format):
    if current_user.user_type != 'STAFF':
        return jsonify({'success': False, 'message': 'Unauthorized'}), 403

    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)
    cursor.execute("SELECT * FROM sitin_sessions")
    sessions = cursor.fetchall()
    connection.close()

    if format == 'csv':
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(['Student ID', 'PC Number', 'Start Time', 'End Time', 'Time Limit'])
        for session in sessions:
            writer.writerow([session['student_id'], session['pc_number'], session['start_time'], session['end_time'], session['time_limit']])
        output.seek(0)
        return send_file(io.BytesIO(output.getvalue().encode()), mimetype='text/csv', as_attachment=True, download_name='sitin_sessions.csv')
    elif format == 'excel':
        # Implement Excel export logic
        pass
    elif format == 'pdf':
        # Implement PDF export logic
        pass
    else:
        return jsonify({'success': False, 'message': 'Invalid format'}), 400

# Get Feedback Route
@app.route('/get_feedback')
@login_required
def get_feedback():
    if current_user.user_type != 'STAFF':
        return jsonify({'success': False, 'message': 'Unauthorized'}), 403

    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)
    cursor.execute("SELECT * FROM feedback ORDER BY date DESC")
    feedback = cursor.fetchall()
    connection.close()

    return jsonify({'success': True, 'feedback': feedback})

# Get Statistics Route
@app.route('/get_statistics')
@login_required
def get_statistics():
    if current_user.user_type != 'STAFF':
        return jsonify({'success': False, 'message': 'Unauthorized'}), 403

    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)
    cursor.execute("SELECT COUNT(*) AS total_sessions FROM sitin_sessions")
    total_sessions = cursor.fetchone()['total_sessions']
    cursor.execute("SELECT COUNT(DISTINCT student_id) AS unique_students FROM sitin_sessions")
    unique_students = cursor.fetchone()['unique_students']
    connection.close()

    statistics = [
        {'name': 'Total Sessions', 'value': total_sessions},
        {'name': 'Unique Students', 'value': unique_students}
    ]

    return jsonify({'success': True, 'statistics': statistics})

# Create Announcement Route
@app.route('/create_announcement', methods=['POST'])
@login_required
def create_announcement():
    if current_user.user_type != 'STAFF':
        return jsonify({'success': False, 'message': 'Unauthorized'}), 403

    data = request.json
    text = data.get('text')

    if not text:
        return jsonify({'success': False, 'message': 'Announcement text is required'}), 400

    connection = get_db_connection()
    cursor = connection.cursor()
    cursor.execute("INSERT INTO announcements (text, date) VALUES (%s, %s)", (text, datetime.now()))
    connection.commit()
    connection.close()

    return jsonify({'success': True})

# Check and update database schema
def check_and_update_schema():
    connection = get_db_connection()
    cursor = connection.cursor()
    
    # Create feedback table if it doesn't exist
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS feedback (
            id INT AUTO_INCREMENT PRIMARY KEY,
            message TEXT NOT NULL,
            date DATETIME NOT NULL,
            student_id VARCHAR(50),
            FOREIGN KEY (student_id) REFERENCES users(IDNO)
        )
    """)
    
    # Create sitin_sessions table if it doesn't exist
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sitin_sessions (
            id INT AUTO_INCREMENT PRIMARY KEY,
            student_id VARCHAR(50) NOT NULL,
            pc_number VARCHAR(10) NOT NULL,
            start_time DATETIME NOT NULL,
            end_time DATETIME,
            time_limit INT NOT NULL,
            purpose VARCHAR(50),
            lab VARCHAR(50),
            FOREIGN KEY (student_id) REFERENCES users(IDNO)
        )
    """)
    
    # Create announcements table if it doesn't exist
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS announcements (
            id INT AUTO_INCREMENT PRIMARY KEY,
            text TEXT NOT NULL,
            date DATETIME NOT NULL,
            staff_id VARCHAR(50),
            FOREIGN KEY (staff_id) REFERENCES users(IDNO)
        )
    """)
    
    # Check if purpose column exists in sitin_sessions
    cursor.execute("SHOW COLUMNS FROM sitin_sessions LIKE 'purpose'")
    purpose_exists = cursor.fetchone() is not None
    
    # Check if lab column exists in sitin_sessions
    cursor.execute("SHOW COLUMNS FROM sitin_sessions LIKE 'lab'")
    lab_exists = cursor.fetchone() is not None
    
    # Add missing columns if needed
    if not purpose_exists:
        cursor.execute("ALTER TABLE sitin_sessions ADD COLUMN purpose VARCHAR(50)")
    
    if not lab_exists:
        cursor.execute("ALTER TABLE sitin_sessions ADD COLUMN lab VARCHAR(50)")
    
    connection.commit()
    connection.close()

# Initialize the app
if __name__ == '__main__':
    check_and_update_schema()
    app.run(debug=True)