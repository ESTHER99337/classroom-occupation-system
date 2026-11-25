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

        # Room booking & release notifications table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                room_name TEXT NOT NULL,
                event_type TEXT NOT NULL,
                message TEXT NOT NULL,
                actor_email TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
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


def add_notification(room_name, event_type, message, actor_email='System'):
    """Records a room booking or release event in the notifications table."""
    try:
        with sqlite3.connect(DB_NAME) as conn:
            cursor = conn.cursor()
            cursor.execute(
                '''
                INSERT INTO notifications (room_name, event_type, message, actor_email)
                VALUES (?, ?, ?, ?)
                ''',
                (room_name, event_type, message, actor_email),
            )
            conn.commit()
    except Exception:
        pass


def get_notifications_data(limit=15):
    """Returns (unread_count, latest_id, rows) from the notifications table."""
    try:
        with sqlite3.connect(DB_NAME) as conn:
            cursor = conn.cursor()
            cursor.execute(
                'SELECT id, room_name, event_type, message, actor_email, created_at '
                'FROM notifications ORDER BY id DESC LIMIT ?',
                (limit,),
            )
            rows = cursor.fetchall()

            cursor.execute('SELECT COALESCE(MAX(id), 0) FROM notifications')
            latest_id = cursor.fetchone()[0]

            cursor.execute(
                'SELECT COUNT(*) FROM notifications WHERE id > ?',
                (str_lit.session_state.last_seen_notif_id,),
            )
            unread_count = cursor.fetchone()[0]

            return unread_count, latest_id, rows
    except Exception:
        return 0, 0, []


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
                'SELECT id, room_name, booking_date, start_time, end_time FROM room_reservations'
            )
            reservations = cursor.fetchall()

            expired_rows = []
            for res_id, r_name, b_date, s_time, end_time_str in reservations:
                if not b_date:
                    continue

                try:
                    if b_date < current_date_str:
                        expired_rows.append(
                            (res_id, r_name, b_date, s_time, end_time_str)
                        )
                        continue

                    if b_date == current_date_str:
                        end_mins = parse_to_minutes(end_time_str)
                        if current_time_mins >= end_mins:
                            expired_rows.append(
                                (res_id, r_name, b_date, s_time, end_time_str)
                            )
                except Exception:
                    pass

            if expired_rows:
                cursor.executemany(
                    'DELETE FROM room_reservations WHERE id = ?',
                    [(row[0],) for row in expired_rows],
                )
                conn.commit()

                for _, r_name, b_date, s_time, end_time_str in expired_rows:
                    add_notification(
                        r_name,
                        'RELEASED',
                        f'{r_name} automatically released after {b_date} ({s_time} - {end_time_str}).',
                        'System',
                    )
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

if 'last_seen_notif_id' not in str_lit.session_state:
    str_lit.session_state.last_seen_notif_id = 0

if 'show_notifications' not in str_lit.session_state:
    str_lit.session_state.show_notifications = False

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
        font-size: 60px !important;
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
.block-container,
    .stMainBlockContainer {
        padding-top: 3.5rem !important;
        margin-top: 0.5rem !important;
    }

    /* Prevent button clipping at top of main view */
    [data-testid="stMainBlockContainer"] .stButton > button {
        margin-top: 0.4rem !important;
        min-height: 2.8rem !important;
    }
    /* Hover effect */
    .stButton > button:hover,
    .stFormSubmitButton > button:hover {
        background-color: #1D4ED8 !important;
        color: #FFFFFF !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# =====================================================================
# SIDEBAR CONTENT
# =====================================================================
with str_lit.sidebar:
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
            str_lit.session_state.show_notifications = False
            str_lit.rerun()


# =====================================================================
# MAIN CONTENT AREA
# =====================================================================
if not str_lit.session_state.logged_in:
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
    # --- TOP HEADER WITH NOTIFICATION BELL & UNREAD BADGE ---
    unread_count, latest_id, notif_rows = get_notifications_data(limit=15)

    top_left, top_right = str_lit.columns([8, 2])
    with top_left:
        str_lit.markdown(
            f'### Hi **{str_lit.session_state.user_email}**, welcome!'
        )
    with top_right:
        bell_label = f'🔔 ({unread_count})' if unread_count > 0 else '🔔'
        if str_lit.button(
            bell_label, key='notif_bell_btn', use_container_width=True
        ):
            str_lit.session_state.show_notifications = (
                not str_lit.session_state.show_notifications
            )
            if str_lit.session_state.show_notifications:
                str_lit.session_state.last_seen_notif_id = latest_id
            str_lit.rerun()

    if str_lit.session_state.show_notifications:
        with str_lit.container(border=True):
            hdr_col, close_col = str_lit.columns([8, 2])
            with hdr_col:
                str_lit.markdown('#### Notifications (Bookings & Releases)')
            with close_col:
                if str_lit.button('Close', key='close_notif_btn'):
                    str_lit.session_state.show_notifications = False
                    str_lit.rerun()

            if not notif_rows:
                str_lit.info('No notifications yet.')
            else:
                for _, r_name, ev_type, msg, actor, created_at in notif_rows:
                    icon = '🟢' if ev_type == 'BOOKED' else '🔵'
                    str_lit.markdown(
                        f'{icon} **{ev_type} — {r_name}**: {msg}  \n'
                        f'<small>By {actor or "System"} • {created_at}</small>',
                        unsafe_allow_html=True,
                    )
                    str_lit.divider()

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

        # -----------------------------------------------------------------
        # VIEW 1: SEARCH SPECIFIC ROOM & BOOK
        # -----------------------------------------------------------------
        if student_mode == 'Search Specific Room':
            with sqlite3.connect(DB_NAME) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    'SELECT DISTINCT room_name FROM timetable WHERE room_name != '
                    '"Unknown" AND room_name IS NOT NULL ORDER BY room_name'
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

                selected_mins = parse_to_minutes(selected_time_str)

                # --- FORM TO ANNOUNCE INTENTION TO OCCUPY ---
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

                        if new_start_mins >= new_end_mins:
                            str_lit.error(
                                'Invalid Time Slot: End time must be after the start time.'
                            )
                        else:
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
                                            f'Official Class Scheduled: {c_code} '
                                            f'with {inst} ({s_time} - {e_time})'
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
                                                f'Already Booked by Student: '
                                                f'{r_email} for {r_cap} '
                                                f'students ({r_start} - {r_end})'
                                            )
                                            break

                            if has_conflict:
                                str_lit.error(
                                    f'Booking Conflict Detected! {conflict_reason}. '
                                    'Please choose a different time slot or classroom.'
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

                                add_notification(
                                    selected_room,
                                    'BOOKED',
                                    f'{selected_room} booked for {date_str_val} ({day_name_val}) '
                                    f'[{start_str_val} - {end_str_val}] for {int(occ_capacity)} students.',
                                    str_lit.session_state.user_email,
                                )

                                str_lit.success(
                                    f'Success! {selected_room} booked for '
                                    f'{date_str_val} ({day_name_val}) from '
                                    f'{start_str_val} to {end_str_val}.'
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
                            if status == 'Free All Day':
                                status = 'Available Now'
                            if next_class is None:
                                next_class = {
                                    'course_code': course_code,
                                    'start_time': start_str,
                                    'end_time': end_str,
                                }

                    if status == 'Free All Day' and schedules:
                        status = 'Available (Classes Ended)'

                    if status == 'Occupied':
                        str_lit.error(
                            f'Status at {selected_time_str}: OCCUPIED by {current_class["course_code"]} '
                            f'({current_class["start_time"]} - {current_class["end_time"]})'
                        )
                    elif next_class:
                        str_lit.success(
                            f'Status at {selected_time_str}: AVAILABLE until {next_class["start_time"]} '
                            f'(Next: {next_class["course_code"]})'
                        )
                    else:
                        str_lit.success(
                            f'Status at {selected_time_str}: {status.upper()}'
                        )

                    str_lit.subheader(
                        f'Full Schedule for {selected_room} ({selected_day})'
                    )
                    combined_rows = []
                    for c_code, s_t, e_t, inst in schedules:
                        combined_rows.append(
                            {
                                'Type': 'Official Class',
                                'Course / Booked By': c_code,
                                'Date': 'Weekly',
                                'Start': s_t,
                                'End': e_t,
                                'Details / Capacity': inst or '-',
                            }
                        )
                    for u_email, s_t, e_t, b_date, cap in reservations:
                        combined_rows.append(
                            {
                                'Type': 'Student Booking',
                                'Course / Booked By': u_email,
                                'Date': b_date or '-',
                                'Start': s_t,
                                'End': e_t,
                                'Details / Capacity': f'{cap} Students',
                            }
                        )

                    if combined_rows:
                        str_lit.dataframe(
                            pd.DataFrame(combined_rows),
                            use_container_width=True,
                            hide_index=True,
                        )
                    else:
                        str_lit.info(
                            f'No classes or student bookings found for {selected_room} on {selected_day}.'
                        )

        # -----------------------------------------------------------------
        # VIEW 2: VIEW ALL ROOMS OVERVIEW
        # -----------------------------------------------------------------
        elif student_mode == 'View All Rooms Overview':
            str_lit.subheader('All Classrooms Overview')
            ov_col1, ov_col2 = str_lit.columns(2)
            with ov_col1:
                ov_day = str_lit.selectbox(
                    'Day of Week',
                    [
                        'Monday',
                        'Tuesday',
                        'Wednesday',
                        'Thursday',
                        'Friday',
                        'Saturday',
                        'Sunday',
                    ],
                    key='ov_day',
                )
            with ov_col2:
                ov_time = str_lit.text_input(
                    'Check Time (e.g., 10:00 AM)',
                    value='10:00 AM',
                    key='ov_time',
                )

            ov_mins = parse_to_minutes(ov_time)
            today_str = datetime.now().strftime('%Y-%m-%d')

            with sqlite3.connect(DB_NAME) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    'SELECT DISTINCT room_name FROM timetable WHERE room_name != '
                    '"Unknown" AND room_name IS NOT NULL ORDER BY room_name'
                )
                all_rooms = [r[0] for r in cursor.fetchall()]

                overview_data = []
                for room in all_rooms:
                    cursor.execute(
                        'SELECT course_code, start_time, end_time FROM timetable '
                        'WHERE room_name = ? AND day_of_week COLLATE NOCASE = ?',
                        (room, ov_day),
                    )
                    tt_rows = cursor.fetchall()

                    cursor.execute(
                        'SELECT user_email, start_time, end_time FROM room_reservations '
                        'WHERE room_name = ? AND (booking_date = ? OR day_of_week COLLATE NOCASE = ?)',
                        (room, today_str, ov_day),
                    )
                    res_rows = cursor.fetchall()

                    room_status = 'Available'
                    activity = 'Free'

                    for c_code, s_t, e_t in tt_rows:
                        if parse_to_minutes(s_t) <= ov_mins < parse_to_minutes(e_t):
                            room_status = 'Occupied (Class)'
                            activity = f'{c_code} ({s_t} - {e_t})'
                            break

                    if room_status == 'Available':
                        for u_email, s_t, e_t in res_rows:
                            if parse_to_minutes(s_t) <= ov_mins < parse_to_minutes(e_t):
                                room_status = 'Occupied (Student Booking)'
                                activity = f'{u_email} ({s_t} - {e_t})'
                                break

                    overview_data.append(
                        {
                            'Classroom': room,
                            'Status': room_status,
                            'Current Activity': activity,
                        }
                    )

            if overview_data:
                str_lit.dataframe(
                    pd.DataFrame(overview_data),
                    use_container_width=True,
                    hide_index=True,
                )
            else:
                str_lit.info('No classrooms available in the database.')

        # -----------------------------------------------------------------
        # VIEW 3: MANAGE MY BOOKINGS (WITH ROOM RELEASE)
        # -----------------------------------------------------------------
        elif student_mode == 'Manage My Bookings':
            str_lit.subheader('My Active Room Bookings')

            with sqlite3.connect(DB_NAME) as conn:
                df_my_bookings = pd.read_sql_query(
                    '''
                    SELECT id AS "Booking ID", room_name AS "Room",
                           booking_date AS "Date", day_of_week AS "Day",
                           start_time AS "Start Time", end_time AS "End Time",
                           capacity AS "Capacity"
                    FROM room_reservations
                    WHERE user_email = ?
                    ORDER BY booking_date ASC, start_time ASC
                    ''',
                    conn,
                    params=(str_lit.session_state.user_email,),
                )

            if df_my_bookings.empty:
                str_lit.info('You do not have any active room bookings.')
            else:
                str_lit.dataframe(
                    df_my_bookings, use_container_width=True, hide_index=True
                )

                str_lit.markdown('---')
                str_lit.markdown('### Release a Booked Room')
                booking_ids = df_my_bookings['Booking ID'].tolist()
                selected_release_id = str_lit.selectbox(
                    'Select Booking ID to Release', booking_ids
                )

                if str_lit.button('Release Room Now'):
                    with sqlite3.connect(DB_NAME) as conn:
                        cursor = conn.cursor()
                        cursor.execute(
                            'SELECT room_name, booking_date, day_of_week, start_time, end_time '
                            'FROM room_reservations WHERE id = ? AND user_email = ?',
                            (
                                int(selected_release_id),
                                str_lit.session_state.user_email,
                            ),
                        )
                        row = cursor.fetchone()

                        if row:
                            r_room, r_date, r_day, r_start, r_end = row
                            cursor.execute(
                                'DELETE FROM room_reservations WHERE id = ?',
                                (int(selected_release_id),),
                            )
                            conn.commit()

                            add_notification(
                                r_room,
                                'RELEASED',
                                f'{r_room} released for {r_date} ({r_day}) [{r_start} - {r_end}].',
                                str_lit.session_state.user_email,
                            )

                            str_lit.success(
                                f'Released {r_room} ({r_date}, {r_start} - {r_end}).'
                            )
                            str_lit.rerun()
                        else:
                            str_lit.error('Booking not found.')

        # -----------------------------------------------------------------
        # VIEW 4: REPORTS & ANALYTICS
        # -----------------------------------------------------------------
        elif student_mode == 'Reports & Analytics':
            str_lit.subheader('Classroom Utilization Summary')

            with sqlite3.connect(DB_NAME) as conn:
                df_res_stats = pd.read_sql_query(
                    '''
                    SELECT room_name AS "Classroom",
                           COUNT(*) AS "Active Bookings",
                           COALESCE(SUM(capacity), 0) AS "Total Students Planned"
                    FROM room_reservations
                    GROUP BY room_name
                    ORDER BY "Active Bookings" DESC
                    ''',
                    conn,
                )

            if df_res_stats.empty:
                str_lit.info('No active student reservations to analyze yet.')
            else:
                str_lit.dataframe(
                    df_res_stats, use_container_width=True, hide_index=True
                )