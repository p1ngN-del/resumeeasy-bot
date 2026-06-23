#!/usr/bin/env python3
from flask import Flask
from config import logger
from database import init_db
from handlers import register_routes
from web import web_bp
import sqlite3
from datetime import datetime

# ===== КОНФИГУРАЦИЯ =====
DB_NAME = "resumeeasy.db"

# ===== ВСТАВИТЬ ПОСЛЕ ИМПОРТОВ =====
def ensure_user_exists(user_id, username="unknown", first_name=""):
    """Проверяет, есть ли пользователь в БД. Если нет — создаёт."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    # Проверяем, есть ли пользователь
    cursor.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,))
    if not cursor.fetchone():
        # Создаём пользователя
        cursor.execute('''
            INSERT INTO users (user_id, username, first_name, join_date, last_activity)
            VALUES (?, ?, ?, ?, ?)
        ''', (user_id, username, first_name, datetime.now().isoformat(), datetime.now().isoformat()))
        conn.commit()
        print(f"✅ Создан пользователь {user_id} ({username}) в БД")
    conn.close()
    return True


app = Flask(__name__)

# Telegram бот и отчёты
register_routes(app)

# Веб-сайт (лендинг + загрузка)
app.register_blueprint(web_bp)

init_db()
logger.info("🚀 Started")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)