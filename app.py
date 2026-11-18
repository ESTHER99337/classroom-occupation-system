from datetime import datetime, time
import os
import pandas as pd
import pdfplumber
import sqlite3
import streamlit as str_lit

DB_NAME = 'timetable.db'


def init_db():
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()

        # Timetable table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS timetable (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                room_name TEXT NOT NULL,
                day_of_week TEXT NOT NULL,
                start_time TEXT NOT NULL,
                end_time TEXT NOT NULL,
                course_code TEXT NOT NULL,
                instructor TEXT
            )
        ''')

        # Users table for individual accounts
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL,
                role TEXT NOT NULL
            )
        ''')

        # Student room reservations table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS room_reservations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                room_name TEXT NOT NULL,
                user_email TEXT NOT NULL,
                day_of_week TEXT NOT NULL,
                booking_date TEXT,
                start_time TEXT NOT NULL,
                end_time TEXT NOT NULL,
                capacity INTEGER DEFAULT 30,
                timestamp TEXT
            )
        ''')

        # Migration checks
        try:
            cursor.execute(
                'ALTER TABLE room_reservations ADD COLUMN capacity INTEGER DEFAULT 30'
            )
        except sqlite3.OperationalError:
            pass

        try:
            cursor.execute(
                'ALTER TABLE room_reservations ADD COLUMN booking_date TEXT'
            )
        except sqlite3.OperationalError:
            pass

        # Default admin account
        cursor.execute(
            'INSERT OR IGNORE INTO users (email, password, role) VALUES (?, ?, ?)',
            ('admin@university.edu', 'admin123', 'Admin'),
        )
        conn.commit()


init_db()


def parse_to_minutes(time_str):
    """Helper function to convert time strings (HH:MM or AM/PM) to total minutes from midnight."""
    try:
        time_str = (
            str(time_str)
            .strip()
            .upper()
            .replace('.', ':')
            .replace(' ', '')
        )
        if 'AM' in time_str or 'PM' in time_str:
            is_pm = 'PM' in time_str
            time_clean = time_str.replace('AM', '').replace('PM', '')
            parts = time_clean.split(':')
            h = int(parts[0])
            m = int(parts[1]) if len(parts) > 1 else 0
            if is_pm and h < 12:
                h += 12
            if not is_pm and h == 12:
                h = 0
            return h * 60 + m
        else:
            time_clean = time_str
            parts = time_clean.split(':')
            h = int(parts[0])
            m = int(parts[1]) if len(parts) > 1 else 0
            return h * 60 + m
    except Exception:
        return 0


def auto_expire_reservations():
    """Automatically removes student room reservations whose date and end time have passed."""
    try:
        now = datetime.now()
        current_date_str = now.strftime('%Y-%m-%d')
        current_time_mins = now.hour * 60 + now.minute

        with sqlite3.connect(DB_NAME) as conn:
            cursor = conn.cursor()
            cursor.execute(
                'SELECT id, booking_date, end_time FROM room_reservations'
            )
            reservations = cursor.fetchall()

            expired_ids = []
            for res_id, b_date, end_time_str in reservations:
                if not b_date:
                    continue

                try:
                    if b_date < current_date_str:
                        expired_ids.append(res_id)
                        continue

                    if b_date == current_date_str:
                        end_mins = parse_to_minutes(end_time_str)
                        if current_time_mins >= end_mins:
                            expired_ids.append(res_id)
                except Exception:
                    pass

            if expired_ids:
                cursor.executemany(
                    'DELETE FROM room_reservations WHERE id = ?',
                    [(i,) for i in expired_ids],
                )
                conn.commit()
    except Exception:
        pass


# Run auto-expiration check on startup
auto_expire_reservations()

str_lit.set_page_config(
    page_title='Classroom Occupancy System', layout='wide'
)

# --- 1. INITIALIZE SESSION STATE ---
if 'logged_in' not in str_lit.session_state:
    str_lit.session_state.logged_in = False
    str_lit.session_state.user_role = None
    str_lit.session_state.user_email = ''

# --- RESPONSIVE DARK AND LIGHT THEME CSS ---
str_lit.markdown(
    """
    <style>
    /* DARK MODE */
[data-theme="dark"] .stApp,
[data-theme="dark"] [data-testid="stAppViewContainer"],
[data-theme="dark"] [data-testid="stMain"] {
    background-color: #0F172A !important;
}

[data-theme="dark"] [data-testid="stSidebar"] {
    background-color: #1E293B !important;
}

/* LIGHT MODE */
[data-theme="light"] .stApp,
[data-theme="light"] [data-testid="stAppViewContainer"],
[data-theme="light"] [data-testid="stMain"] {
    background-color: #FFFFFF !important;
}

[data-theme="light"] [data-testid="stSidebar"] {
    background-color: #F1F5F9 !important;
}

    /* All normal text */
    h1, h2, h3, h4, h5, h6,
    p, label, span, li {
        color: var(--text-color);
    }
    /* Font sizes */
    h1, .stTitle {
        font-size: 40px !important;
        font-weight: 800 !important;
    }

    h2 {
        font-size: 26px !important;
        font-weight: 700 !important;
    }

    h3 {
        font-size: 20px !important;
        font-weight: 600 !important;
    }

    p, label, button, input {
        font-size: 18px !important;
    }

    .stDataFrame, table {
        font-size: 15px !important;
    }

    .block-container,
    .stMainBlockContainer {
        padding-top: 2rem !important;
        margin-top: 0rem !important;
    }

    </style>
    """,
    unsafe_allow_html=True
)

# =====================================================================
# SIDEBAR CONTENT
# =====================================================================
with str_lit.sidebar:
    if os.path.exists('banner.png'):
        str_lit.image('banner.png', use_container_width=True)

    str_lit.markdown('---')

    if not str_lit.session_state.logged_in:
        str_lit.markdown('### Portal Action')
        auth_mode = str_lit.radio(
            'Choose Action', ['Login', 'Create Account (Sign Up)']
        )
    else:
        auth_mode = None
        str_lit.markdown('### Navigation & Profile')
        str_lit.write(f'**User:** {str_lit.session_state.user_email}')
        str_lit.write(f'**Role:** {str_lit.session_state.user_role}')

        str_lit.markdown('---')
        if str_lit.button('Log out of System', use_container_width=True):
            str_lit.session_state.logged_in = False
            str_lit.session_state.user_role = None
            str_lit.session_state.user_email = ''
            str_lit.rerun()


# =====================================================================
# MAIN CONTENT AREA
# =====================================================================
if not str_lit.session_state.logged_in:
    str_lit.title('University Classroom Occupancy & Availability System')
    str_lit.markdown('---')

    if auth_mode == 'Login':
        str_lit.subheader('Enter Your Login Credentials')
        with str_lit.form('login_form_main'):
            email_input = str_lit.text_input(
                'School Email Address', placeholder='e.g. name@university.ac.ke'
            )
            password_input = str_lit.text_input(
                'Password', type='password', placeholder='Enter your password'
            )
            submit_login = str_lit.form_submit_button('Login to Portal')

            if submit_login:
                email_input = email_input.strip().lower()
                password_input = password_input.strip()

                if not email_input or not password_input:
                    str_lit.error('Please fill in both fields.')
                else:
                    with sqlite3.connect(DB_NAME) as conn:
                        cursor = conn.cursor()
                        cursor.execute(
                            'SELECT role FROM users WHERE email = ? AND password = ?',
                            (email_input, password_input),
                        )
                        user = cursor.fetchone()

                    if user:
                        role = user[0]
                        str_lit.session_state.logged_in = True
                        str_lit.session_state.user_role = role
                        str_lit.session_state.user_email = email_input
                        str_lit.success(
                            f'Welcome back, {email_input}! Logging in as {role}...'
                        )
                        str_lit.rerun()
                    else:
                        str_lit.error(
                            'Incorrect email or password. Please try again.'
                        )

    else:
        str_lit.subheader('Register a New Account')
        with str_lit.form('signup_form_main'):
            new_email = str_lit.text_input(
                'School Email Address', placeholder='student@university.ac.ke'
            )
            new_password = str_lit.text_input(
                'Create Password', type='password', placeholder='Choose a password'
            )
            selected_role = str_lit.selectbox('Register As', ['Student', 'Admin'])

            admin_secret = ''
            if selected_role == 'Admin':
                admin_secret = str_lit.text_input(
                    'Admin Security Passcode',
                    type='password',
                    placeholder='Required to create admin account',
                )

            submit_signup = str_lit.form_submit_button('Register Account')

            if submit_signup:
                new_email = new_email.strip().lower()
                new_password = new_password.strip()

                if not new_email or not new_password:
                    str_lit.error('Please enter both email and password.')
                elif '@' not in new_email:
                    str_lit.error('Please enter a valid email address.')
                else:
                    if (
                        selected_role == 'Admin'
                        and admin_secret != 'SECRET123'
                    ):
                        str_lit.error('Invalid Admin Security Passcode.')
                    else:
                        try:
                            with sqlite3.connect(DB_NAME) as conn:
                                cursor = conn.cursor()
                                cursor.execute(
                                    'INSERT INTO users (email, password, role) VALUES (?, ?, ?)',
                                    (new_email, new_password, selected_role),
                                )
                                conn.commit()
                            str_lit.success(
                                'Account created successfully! Switch to the Login action in the sidebar to sign in.'
                            )
                        except sqlite3.IntegrityError:
                            str_lit.error(
                                'This email address is already registered. Please log in instead.'
                            )

else:
    str_lit.markdown(f'### Hi **{str_lit.session_state.user_email}**, welcome!')
    str_lit.markdown('---')

    # =====================================================================
    # ADMIN PANEL WORKSPACE
    # =====================================================================
    if str_lit.session_state.user_role == 'Admin':
        admin_tab1, admin_tab2 = str_lit.tabs(
            ['Upload PDF Timetable', 'Manage & Delete Timetables']
        )

        with admin_tab1:
            str_lit.header('Upload Timetable PDF')
            str_lit.write(
                'Upload a PDF document containing the university timetable schedule to update room assignments.'
            )

            uploaded_file = str_lit.file_uploader(
                'Choose a PDF file', type=['pdf']
            )

            if uploaded_file is not None:
                try:
                    all_rows = []
                    with pdfplumber.open(uploaded_file) as pdf:
                        for page in pdf.pages:
                            table = page.extract_table()
                            if table:
                                all_rows.extend(table)

                    if not all_rows or len(all_rows) < 2:
                        str_lit.error(
                            'Could not find valid table rows in this PDF.'
                        )
                    else:
                        df_preview = pd.DataFrame(
                            all_rows[1:], columns=all_rows[0]
                        )
                        str_lit.write('**Preview of extracted PDF rows:**')
                        str_lit.dataframe(df_preview, use_container_width=True)

                        if str_lit.button('Save to Database'):
                            with sqlite3.connect(DB_NAME) as conn:
                                cursor = conn.cursor()

                                success_count = 0
                                for row in all_rows[1:]:
                                    clean_row = [
                                        str(cell).strip()
                                        for cell in row
                                        if cell is not None
                                    ]
                                    if len(clean_row) < 6:
                                        continue

                                    room = clean_row[0]
                                    day = clean_row[1].strip().capitalize()
                                    start = clean_row[2]
                                    end = clean_row[3]
                                    course = clean_row[4]
                                    instructor = clean_row[5]

                                    if room.lower() in [
                                        'room name',
                                        'room_name',
                                        'room',
                                    ]:
                                        continue

                                    cursor.execute(
                                        '''
                                            INSERT INTO timetable (room_name, day_of_week, start_time, end_time, course_code, instructor)
                                            VALUES (?, ?, ?, ?, ?, ?)
                                        ''',
                                        (
                                            room,
                                            day,
                                            start,
                                            end,
                                            course,
                                            instructor,
                                        ),
                                    )
                                    success_count += 1
                                conn.commit()

                            str_lit.success(
                                f'Successfully saved {success_count} rows into the database!'
                            )
                except Exception as e:
                    str_lit.error(f'Error processing PDF file: {e}')

        with admin_tab2:
            str_lit.header('Manage & Delete Uploaded Timetables')

            with sqlite3.connect(DB_NAME) as conn:
                df_all_tt = pd.read_sql_query(
                    """
                        SELECT id AS "ID", room_name AS "Room", day_of_week AS "Day", 
                               start_time AS "Start", end_time AS "End", 
                               course_code AS "Course", instructor AS "Instructor"
                        FROM timetable
                        ORDER BY room_name, day_of_week, start_time
                    """,
                    conn,
                )

            if df_all_tt.empty:
                str_lit.info(
                    'No timetable records currently stored in the database.'
                )
            else:
                str_lit.write(f'**Total Stored Entries:** `{len(df_all_tt)}`')
                str_lit.dataframe(df_all_tt, use_container_width=True)

                str_lit.markdown('---')
                col_del1, col_del2 = str_lit.columns(2)

                with col_del1:
                    str_lit.subheader('Delete Specific Entry')
                    entry_id = str_lit.number_input(
                        'Enter Entry ID to Delete', min_value=1, step=1
                    )
                    if str_lit.button('Delete Entry'):
                        with sqlite3.connect(DB_NAME) as conn:
                            cursor = conn.cursor()
                            cursor.execute(
                                'DELETE FROM timetable WHERE id = ?',
                                (entry_id,),
                            )
                            conn.commit()
                            if cursor.rowcount > 0:
                                str_lit.success(
                                    f'Successfully deleted Entry ID {entry_id}!'
                                )
                                str_lit.rerun()
                            else:
                                str_lit.error(f'Entry ID {entry_id} not found.')

                with col_del2:
                    str_lit.subheader('Delete Entire Room Schedule')
                    rooms_list = sorted(df_all_tt['Room'].unique().tolist())
                    selected_del_room = str_lit.selectbox(
                        'Select Classroom to Purge', rooms_list
                    )
                    if str_lit.button(
                        f'Delete All Schedules for {selected_del_room}'
                    ):
                        with sqlite3.connect(DB_NAME) as conn:
                            cursor = conn.cursor()
                            cursor.execute(
                                'DELETE FROM timetable WHERE room_name = ?',
                                (selected_del_room,),
                            )
                            conn.commit()
                            str_lit.success(
                                f'All schedules for {selected_del_room} deleted!'
                            )
                            str_lit.rerun()

                str_lit.markdown('---')
                str_lit.subheader('Danger Zone')
                if str_lit.button('Clear Entire Timetable Database'):
                    with sqlite3.connect(DB_NAME) as conn:
                        cursor = conn.cursor()
                        cursor.execute('DELETE FROM timetable')
                        conn.commit()
                    str_lit.success(
                        'Entire timetable database has been cleared completely!'
                    )
                    str_lit.rerun()

    # =====================================================================
    # STUDENT PANEL WORKSPACE
    # =====================================================================
    elif str_lit.session_state.user_role == 'Student':
        str_lit.header('Student Workspace: Classroom Availability')

        student_mode = str_lit.radio(
            'Select Dashboard View',
            [
                'Search Specific Room',
                'View All Rooms Overview',
                'Manage My Bookings',
                'Reports & Analytics',
            ],
            horizontal=True,
        )

        if student_mode == 'Search Specific Room':
            with sqlite3.connect(DB_NAME) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    'SELECT DISTINCT room_name FROM timetable WHERE room_name !='
                    ' "Unknown" AND room_name IS NOT NULL ORDER BY room_name'
                )
                rooms = [row[0] for row in cursor.fetchall()]

            if not rooms:
                str_lit.warning(
                    'No valid classrooms found in database. Please ask an admin to upload the timetable PDF first.'
                )
            else:
                selected_room = str_lit.selectbox('Select Classroom', rooms)

                col1, col2 = str_lit.columns(2)
                with col1:
                    selected_day = str_lit.selectbox(
                        'Select Day',
                        [
                            'Monday',
                            'Tuesday',
                            'Wednesday',
                            'Thursday',
                            'Friday',
                            'Saturday',
                            'Sunday',
                        ],
                    )
                with col2:
                    selected_time_str = str_lit.text_input(
                        'Search Time (e.g., 09:00 AM)', value='09:00 AM'
                    )

                # Convert search time to minutes for comparison
                selected_mins = parse_to_minutes(selected_time_str)

                # --- FORM TO ANNOUNCE INTENTION TO OCCUPY (SIMPLE TEXT INPUTS) ---
                str_lit.markdown('---')
                str_lit.markdown('### Announce Intention to Occupy')
                str_lit.write(
                    f'Found **{selected_room}** empty and want to use it? Type the date, time window, and headcount below:'
                )

                with str_lit.form('occupy_announcement_form'):
                    d_col1, d_col2 = str_lit.columns(2)
                    with d_col1:
                        occ_date = str_lit.date_input(
                            'Reservation Date', value='today'
                        )
                    with d_col2:
                        str_lit.write(
                            f'**Day:** {occ_date.strftime("%A") if occ_date else ""}'
                        )

                    c_col1, c_col2, c_col3 = str_lit.columns(3)
                    with c_col1:
                        start_str_val = str_lit.text_input(
                            'Start Time', value='09:00 AM'
                        )
                    with c_col2:
                        end_str_val = str_lit.text_input(
                            'End Time', value='10:00 AM'
                        )
                    with c_col3:
                        occ_capacity = str_lit.number_input(
                            'Student Capacity (Headcount)',
                            min_value=1,
                            max_value=500,
                            value=30,
                        )

                    submit_occupy = str_lit.form_submit_button(
                        'Announce Room Occupation'
                    )

                    if submit_occupy:
                        date_str_val = occ_date.strftime('%Y-%m-%d')
                        day_name_val = occ_date.strftime('%A')

                        new_start_mins = parse_to_minutes(start_str_val)
                        new_end_mins = parse_to_minutes(end_str_val)

                        # Validate time inputs
                        if new_start_mins >= new_end_mins:
                            str_lit.error(
                                'Invalid Time Slot: End time must be after the start time.'
                            )
                        else:
                            # =====================================================
                            # CONFLICT DETECTION ENGINE
                            # =====================================================
                            has_conflict = False
                            conflict_reason = ''

                            with sqlite3.connect(DB_NAME) as conn:
                                cursor = conn.cursor()

                                # 1. Check against official timetable classes
                                cursor.execute(
                                    '''
                                    SELECT course_code, start_time, end_time, instructor 
                                    FROM timetable 
                                    WHERE room_name = ? AND day_of_week COLLATE NOCASE = ?
                                ''',
                                    (selected_room, day_name_val),
                                )
                                official_classes = cursor.fetchall()

                                for (
                                    c_code,
                                    s_time,
                                    e_time,
                                    inst,
                                ) in official_classes:
                                    s_mins = parse_to_minutes(s_time)
                                    e_mins = parse_to_minutes(e_time)

                                    if (
                                        new_start_mins < e_mins
                                        and new_end_mins > s_mins
                                    ):
                                        has_conflict = True
                                        conflict_reason = (
                                            f'Official Class Scheduled: {c_code}'
                                            f' with {inst} ({s_time} -'
                                            f' {e_time})'
                                        )
                                        break

                                # 2. Check against existing student bookings for the same date
                                if not has_conflict:
                                    cursor.execute(
                                        '''
                                        SELECT user_email, start_time, end_time, capacity 
                                        FROM room_reservations 
                                        WHERE room_name = ? AND booking_date = ?
                                    ''',
                                        (selected_room, date_str_val),
                                    )
                                    existing_res = cursor.fetchall()

                                    for (
                                        r_email,
                                        r_start,
                                        r_end,
                                        r_cap,
                                    ) in existing_res:
                                        r_start_mins = parse_to_minutes(r_start)
                                        r_end_mins = parse_to_minutes(r_end)

                                        if (
                                            new_start_mins < r_end_mins
                                            and new_end_mins > r_start_mins
                                        ):
                                            has_conflict = True
                                            conflict_reason = (
                                                f'Already Booked by Student:'
                                                f' {r_email} for {r_cap}'
                                                f' students ({r_start} -'
                                                f' {r_end})'
                                            )
                                            break

                            if has_conflict:
                                str_lit.error(
                                    f'Booking Conflict Detected! {conflict_reason}.'
                                    ' Please choose a different time slot or classroom.'
                                )
                            else:
                                with sqlite3.connect(DB_NAME) as conn:
                                    cursor = conn.cursor()
                                    cursor.execute(
                                        '''
                                        INSERT INTO room_reservations (room_name, user_email, day_of_week, booking_date, start_time, end_time, capacity, timestamp)
                                        VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))
                                    ''',
                                        (
                                            selected_room,
                                            str_lit.session_state.user_email,
                                            day_name_val,
                                            date_str_val,
                                            start_str_val,
                                            end_str_val,
                                            int(occ_capacity),
                                        ),
                                    )
                                    conn.commit()
                                str_lit.success(
                                    f'Success! {selected_room} booked for'
                                    f' {date_str_val} ({day_name_val}) from'
                                    f' {start_str_val} to {end_str_val}.'
                                )
                                str_lit.rerun()

                str_lit.markdown('---')
                if str_lit.button('Check Availability & View Schedule'):
                    with sqlite3.connect(DB_NAME) as conn:
                        cursor = conn.cursor()
                        cursor.execute(
                            '''
                                SELECT course_code, start_time, end_time, instructor 
                                FROM timetable 
                                WHERE room_name = ? AND day_of_week COLLATE NOCASE = ?
                                ORDER BY start_time ASC
                            ''',
                            (selected_room, selected_day),
                        )
                        schedules = cursor.fetchall()

                        cursor.execute(
                            '''
                                SELECT user_email, start_time, end_time, booking_date, capacity FROM room_reservations
                                WHERE room_name = ? AND day_of_week COLLATE NOCASE = ?
                                ORDER BY start_time ASC
                            ''',
                            (selected_room, selected_day),
                        )
                        reservations = cursor.fetchall()

                    status = 'Free All Day'
                    current_class = None
                    next_class = None

                    for course_code, start_str, end_str, instructor in schedules:
                        start_mins = parse_to_minutes(start_str)
                        end_mins = parse_to_minutes(end_str)

                        if start_mins <= selected_mins <= end_mins:
                            status = 'Occupied'
                            current_class = {
                                'course_code': course_code,
                                'start_time': start_str,
                                'end_time': end_str,
                                'instructor': instructor,
                            }
                            break
                        elif selected_mins < start_mins:
                            status = 'Free with Upcoming Class'
                            next_class = {
                                'course_code': course_code,
                                'start_time': start_str,
                                'end_time': end_str,
                                'instructor': instructor,
                            }
                            break

                    for res_user, r_start, r_end, cap, b_date in reservations:
                        r_start_mins = parse_to_minutes(r_start)
                        r_end_mins = parse_to_minutes(r_end)
                        if r_start_mins <= selected_mins <= r_end_mins:
                            status = 'Occupied'
                            current_class = {
                                'course_code': (
                                    f'Student Reservation ({cap} Students)'
                                ),
                                'start_time': r_start,
                                'end_time': r_end,
                                'instructor': res_user,
                            }
                            break

                    str_lit.markdown('---')
                    str_lit.subheader(f'Results for: {selected_room}')
                    str_lit.caption(
                        f'Checked for **{selected_day}** at **{selected_time_str}**'
                    )

                    if status == 'Occupied':
                        str_lit.error(
                            f'**Status: Occupied** (Class or group reservation in session at {selected_time_str})'
                        )
                        if current_class:
                            str_lit.warning(f"""
                            **Ongoing Activity Details:**
                            - **Purpose:** {current_class['course_code']}
                            - **Booked By:** {current_class['instructor']}
                            - **Time:** {current_class['start_time']} - {current_class['end_time']}
                            """)
                    elif status == 'Free with Upcoming Class':
                        str_lit.success(
                            '**Status: Available Right Now** (No class in session)'
                        )
                        if next_class:
                            str_lit.info(f"""
                            **Next Scheduled Event in this Room:**
                            - **Course:** {next_class['course_code']} ({next_class['instructor']})
                            - **Starts At:** {next_class['start_time']}
                            """)
                    else:
                        str_lit.success(
                            '**Status: Available** (Free or open for student use!)'
                        )

                    str_lit.markdown('---')
                    str_lit.write(f'**Full Schedule for {selected_day}:**')

                    schedule_data = []
                    for course, start, end, instructor in schedules:
                        schedule_data.append({
                            'Start Mins': parse_to_minutes(start),
                            'Date': 'Recurring',
                            'Time': f'{start} - {end}',
                            'Course Code / Activity': course,
                            'Instructor / User': instructor,
                            'Capacity': 'N/A (Official)',
                            'Type': 'Official Class',
                        })

                    for res_user, r_start, r_end,b_date, cap in reservations:
                        schedule_data.append({
                            'Start Mins': parse_to_minutes(r_start),
                            'Time': f'{r_start} - {r_end}',
                            'Course Code / Activity': ' Student Group Booking',
                            'Instructor / User': res_user,
                            'Capacity': f'{cap} Students',
                            'Date': b_date if b_date else 'N/A',
                            'Type': 'Student Occupancy',
                        })

                    if schedule_data:
                        schedule_data = sorted(
                            schedule_data, key=lambda x: x['Start Mins']
                        )
                        df_sched = pd.DataFrame(schedule_data).drop(
                            columns=['Start Mins']
                        )
                        str_lit.table(df_sched)
                    else:
                        str_lit.info(
                            f'No classes or reservations scheduled for {selected_day} in this room.'
                        )

        elif student_mode == 'View All Rooms Overview':
            str_lit.write(
                'Check the status of **all classrooms** simultaneously for a given day and time.'
            )

            col1, col2 = str_lit.columns(2)
            with col1:
                overview_day = str_lit.selectbox(
                    'Select Day for Overview',
                    [
                        'Monday',
                        'Tuesday',
                        'Wednesday',
                        'Thursday',
                        'Friday',
                        'Saturday',
                        'Sunday',
                    ],
                    key='overview_day',
                )
            with col2:
                overview_time_str = str_lit.text_input(
                    'Overview Time (e.g., 09:00 AM)',
                    value='09:00 AM',
                    key='ov_time_str',
                )

            # Convert overview time to minutes
            overview_mins = parse_to_minutes(overview_time_str)

            if str_lit.button('Generate All Rooms Overview'):
                with sqlite3.connect(DB_NAME) as conn:
                    cursor = conn.cursor()
                    cursor.execute(
                        'SELECT DISTINCT room_name FROM timetable WHERE room_name !='
                        ' "Unknown" AND room_name IS NOT NULL ORDER BY room_name'
                    )
                    all_rooms = [row[0] for row in cursor.fetchall()]

                if not all_rooms:
                    str_lit.warning('No classrooms found in the database.')
                else:
                    overview_results = []

                    with sqlite3.connect(DB_NAME) as conn:
                        cursor = conn.cursor()
                        for r in all_rooms:
                            cursor.execute(
                                'SELECT user_email, start_time, end_time, capacity FROM'
                                ' room_reservations WHERE room_name = ? AND day_of_week'
                                ' COLLATE NOCASE = ?',
                                (r, overview_day),
                            )
                            res_list = cursor.fetchall()

                            cursor.execute(
                                '''
                                    SELECT course_code, start_time, end_time, instructor 
                                    FROM timetable 
                                    WHERE room_name = ? AND day_of_week COLLATE NOCASE = ?
                                    ORDER BY start_time ASC
                                ''',
                                (r, overview_day),
                            )
                            room_schedules = cursor.fetchall()

                            room_status = ' Available (Free All Day)'
                            current_info = 'None'
                            is_occ = False

                            for r_user, r_start, r_end, cap in res_list:
                                if (
                                    parse_to_minutes(r_start)
                                    <= overview_mins
                                    <= parse_to_minutes(r_end)
                                ):
                                    room_status = (
                                        'Occupied (Group Booking)'
                                    )
                                    current_info = f'Booked by {r_user} for {cap} students ({r_start}-{r_end})'
                                    is_occ = True
                                    break

                            if not is_occ:
                                if not room_schedules:
                                    room_status = 'Free All Day'
                                else:
                                    for c_code, s_str, e_str, inst in (
                                        room_schedules
                                    ):
                                        s_mins = parse_to_minutes(s_str)
                                        e_mins = parse_to_minutes(e_str)

                                        if (
                                            s_mins
                                            <= overview_mins
                                            <= e_mins
                                        ):
                                            room_status = ' Occupied'
                                            current_info = (
                                                f'{c_code} ({s_str}-{e_str})'
                                            )
                                            is_occ = True
                                            break
                                        elif overview_mins < s_mins:
                                            room_status = f' Free (Next: {c_code} @ {s_str})'
                                            is_occ = True
                                            break

                                    if not is_occ:
                                        room_status = ' Free (Rest of Day)'

                            overview_results.append({
                                'Classroom': r,
                                'Status': room_status,
                                'Ongoing / Next Activity': current_info,
                            })

                    str_lit.markdown('---')
                    str_lit.subheader(
                        f'Overview for All Rooms on {overview_day} at {overview_time_str}'
                    )
                    str_lit.table(pd.DataFrame(overview_results))

        elif student_mode == 'Manage My Bookings':
            str_lit.subheader('Manage & Release My Room Bookings')
            str_lit.write(
                'View your active student room bookings below. You can release or delete any booking if your plans change.'
            )

            with sqlite3.connect(DB_NAME) as conn:
                df_my_res = pd.read_sql_query(
                    """
                        SELECT id AS "Booking ID", room_name AS "Room", day_of_week AS "Day", 
                               booking_date AS "Date", start_time AS "Start", end_time AS "End", 
                               capacity AS "Capacity", timestamp AS "Reserved At"
                        FROM room_reservations 
                        WHERE user_email = ?
                        ORDER BY booking_date, start_time
                    """,
                    conn,
                    params=(str_lit.session_state.user_email,),
                )

            if df_my_res.empty:
                str_lit.info(
                    'You currently have no active room bookings or reservations.'
                )
            else:
                str_lit.dataframe(df_my_res, use_container_width=True)

                str_lit.markdown('---')
                col_m1, col_m2 = str_lit.columns(2)

                with col_m1:
                    cancel_id = str_lit.number_input(
                        'Enter Booking ID to Release', min_value=1, step=1
                    )
                    if str_lit.button('Release Selected Booking'):
                        with sqlite3.connect(DB_NAME) as conn:
                            cursor = conn.cursor()
                            cursor.execute(
                                'SELECT id FROM room_reservations WHERE id = ? AND user_email = ?',
                                (
                                    cancel_id,
                                    str_lit.session_state.user_email,
                                ),
                            )
                            found = cursor.fetchone()

                            if found:
                                cursor.execute(
                                    'DELETE FROM room_reservations WHERE id = ?',
                                    (cancel_id,),
                                )
                                conn.commit()
                                str_lit.success(
                                    f'Successfully released Booking ID {cancel_id}!'
                                )
                                str_lit.rerun()
                            else:
                                str_lit.error(
                                    'Invalid Booking ID or you do not own this booking.'
                                )

                with col_m2:
                    str_lit.markdown('### Quick Release All')
                    if str_lit.button('Release All My Bookings'):
                        with sqlite3.connect(DB_NAME) as conn:
                            cursor = conn.cursor()
                            cursor.execute(
                                'DELETE FROM room_reservations WHERE user_email = ?',
                                (str_lit.session_state.user_email,),
                            )
                            conn.commit()
                        str_lit.success(
                            'All your active bookings have been released!'
                        )
                        str_lit.rerun()

        else:
            str_lit.subheader('Classroom Occupancy Reports & Analytics')
            str_lit.write(
                'Review overall metrics and download summary reports for university room allocation.'
            )
            str_lit.markdown('---')

            with sqlite3.connect(DB_NAME) as conn:
                df_summary = pd.read_sql_query(
                    """
                        SELECT 
                            room_name AS "Classroom",
                            COUNT(*) AS "Total Scheduled Classes"
                        FROM timetable 
                        GROUP BY room_name
                        ORDER BY "Total Scheduled Classes" DESC
                    """,
                    conn,
                )

            if df_summary.empty:
                str_lit.info(
                    'No timetable data available to generate reports. Please upload a timetable PDF first.'
                )
            else:
                col1, col2 = str_lit.columns(2)
                with col1:
                    str_lit.metric(
                        label='Total Tracked Rooms',
                        value=len(df_summary['Classroom'].unique()),
                    )
                with col2:
                    str_lit.metric(
                        label='Total Weekly Classes Scheduled',
                        value=int(df_summary['Total Scheduled Classes'].sum()),
                    )

                str_lit.markdown('#### Scheduled Classes per Classroom')
                chart_data = df_summary.set_index('Classroom')[
                    'Total Scheduled Classes'
                ]
                str_lit.bar_chart(chart_data)

                str_lit.markdown('#### Summary Data Table')
                str_lit.dataframe(df_summary, use_container_width=True)

                csv_data = df_summary.to_csv(index=False).encode('utf-8')
                str_lit.download_button(
                    label='Download Summary Report (CSV)',
                    data=csv_data,
                    file_name='classroom_occupancy_summary.csv',
                    mime='text/csv',
                )