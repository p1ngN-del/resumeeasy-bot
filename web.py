import uuid
import logging
import json
from datetime import datetime
from flask import Blueprint, request, render_template_string, jsonify, Response

from database import save_analysis, save_user, get_db
from ai import analyze_part
from telegram_helpers import extract_json
from handlers import extract_text_from_pdf, report_cache, resume_cache
from templates_landing import LANDING_HTML

logger = logging.getLogger(__name__)
web_bp = Blueprint('web', __name__)


def ensure_user_exists_for_web(user_id, username="web_user", first_name="Web Upload"):
    """Проверяет, есть ли пользователь в БД. Если нет — создаёт."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM users WHERE user_id = %s", (user_id,))
    if not cursor.fetchone():
        cursor.execute('''
            INSERT INTO users (user_id, username, first_name, join_date, last_activity)
            VALUES (%s, %s, %s, %s, %s)
        ''', (user_id, username, first_name, datetime.now().isoformat(), datetime.now().isoformat()))
        conn.commit()
        logger.info(f"✅ Создан web-пользователь {user_id}")
    conn.close()


@web_bp.route('/')
def landing():
    """Главная страница с загрузкой резюме"""
    return render_template_string(LANDING_HTML)


@web_bp.route('/api/analyze', methods=['POST'])
def api_analyze():
    """Загрузка PDF с сайта и мгновенный анализ"""

    if 'file' not in request.files:
        return jsonify({"error": "Файл не найден"}), 400

    file = request.files['file']

    if file.filename == '':
        return jsonify({"error": "Файл не выбран"}), 400

    if not file.filename.lower().endswith('.pdf'):
        return jsonify({"error": "Принимаются только PDF файлы"}), 400

    try:
        file_bytes = file.read()

        if len(file_bytes) > 10 * 1024 * 1024:
            return jsonify({"error": "Файл больше 10 МБ"}), 400

        # Извлекаем текст из PDF
        resume_text = extract_text_from_pdf(file_bytes)

        if not resume_text or len(resume_text.split()) < 50:
            return jsonify({
                "error": "Не удалось извлечь текст из PDF. Попробуйте другой файл."
            }), 400

        logger.info(f"Web upload: extracted {len(resume_text)} chars")

        # Создаём web-пользователя
        web_user_id = int(datetime.now().timestamp() * 1000000)
        ensure_user_exists_for_web(web_user_id)

        # Анализируем резюме через AI
        result = analyze_part(resume_text, "full_report", timeout=90)
        data = extract_json(result)

        if not data:
            return jsonify({
                "error": "Не удалось проанализировать резюме. Попробу