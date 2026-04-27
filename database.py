import psycopg2
import psycopg2.extras
from config import DATABASE_URL, logger

def get_db():
    return psycopg2.connect(DATABASE_URL)

def init_db():
    conn = get_db()
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        user_id BIGINT PRIMARY KEY, 
        username TEXT, 
        first_name TEXT,
        join_date TIMESTAMP DEFAULT NOW(), 
        last_activity TIMESTAMP DEFAULT NOW()
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS analyses (
        id SERIAL PRIMARY KEY, 
        user_id BIGINT REFERENCES users(user_id),
        resume_text TEXT, 
        ats_score INTEGER, 
        overall_score INTEGER,
        analysis_type TEXT, 
        analysis_date TIMESTAMP DEFAULT NOW()
    )''')
    conn.commit()
    conn.close()
    logger.info("Database tables initialized")

def save_user(user_id, username, first_name):
    conn = get_db()
    c = conn.cursor()
    c.execute('''INSERT INTO users (user_id, username, first_name, join_date, last_activity)
        VALUES (%s, %s, %s, NOW(), NOW())
        ON CONFLICT (user_id) DO UPDATE SET 
        username = EXCLUDED.username,
        first_name = EXCLUDED.first_name,
        last_activity = NOW()''',
        (user_id, username, first_name))
    conn.commit()
    conn.close()

def save_analysis(user_id, resume_text, ats, overall, a_type="standard"):
    conn = get_db()
    c = conn.cursor()
    c.execute('''INSERT INTO analyses (user_id, resume_text, ats_score, overall_score, analysis_type, analysis_date)
        VALUES (%s, %s, %s, %s, %s, NOW())''',
        (user_id, resume_text[:500], ats, overall, a_type))
    conn.commit()
    conn.close()

def get_user_history(user_id, limit=5):
    conn = get_db()
    c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    c.execute('''SELECT analysis_date, ats_score, overall_score, analysis_type
        FROM analyses WHERE user_id=%s ORDER BY id DESC LIMIT %s''', (user_id, limit))
    rows = c.fetchall()
    conn.close()
    return rows

def get_last_analysis_text(user_id):
    conn = get_db()
    c = conn.cursor()
    c.execute('''SELECT resume_text FROM analyses WHERE user_id=%s ORDER BY id DESC LIMIT 1''', (user_id,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else ""

def get_all_users(limit=10):
    conn = get_db()
    c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    c.execute('''SELECT u.user_id, u.username, u.first_name, u.join_date, u.last_activity,
        COUNT(a.id) as total, COALESCE(AVG(a.ats_score), 0) as avg_ats
        FROM users u LEFT JOIN analyses a ON u.user_id = a.user_id
        GROUP BY u.user_id ORDER BY u.last_activity DESC LIMIT %s''', (limit,))
    rows = c.fetchall()
    conn.close()
    return rows
