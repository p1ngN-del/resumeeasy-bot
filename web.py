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
                "error": "Не удалось проанализировать резюме. Попробуйте позже."
            }), 500

        # Сохраняем анализ
        save_analysis(
            web_user_id,
            resume_text,
            data.get('ats_score', 0),
            data.get('overall_score', 0),
            "web_upload"
        )

        # Кладём отчёт во временный кэш
        report_id = str(uuid.uuid4())

        report_cache[report_id] = {
            'type': 'full',
            'user_id': web_user_id,
            'date': datetime.now().strftime('%d.%m.%Y %H:%M'),
            'overall': data.get('overall_score', 0),
            'ats': data.get('ats_score', 0),
            'keywords': data.get('keywords', []),
            'headlines': data.get('headlines', []),
            'critical_fixes': data.get('critical_fixes', []),
            'metrics_fixes': data.get('metrics_fixes', []),
            'style_fixes': data.get('style_fixes', []),
            'hh_rec': data.get('hh_recommendations', ''),
            'match_vac': data.get('match_vacancies', []),
            'verdict': data.get('verdict', '')
        }

        resume_cache[web_user_id] = resume_text

        return jsonify({"redirect": f"/report/{report_id}"})

    except Exception as e:
        logger.error(f"Web analyze error: {e}", exc_info=True)
        return jsonify({
            "error": f"Ошибка сервера: {str(e)[:100]}"
        }), 500


@web_bp.route('/api/analyze-stream', methods=['POST'])
def api_analyze_stream():
    """Загрузка PDF с сайта с прогрессом"""

    if 'file' not in request.files:
        return jsonify({"error": "Файл не найден"}), 400

    file = request.files['file']

    if file.filename == '':
        return jsonify({"error": "Файл не выбран"}), 400

    if not file.filename.lower().endswith('.pdf'):
        return jsonify({"error": "Принимаются только PDF файлы"}), 400

    def generate():
        try:
            yield f"data: {json.dumps({'stage': 'Читаю PDF...', 'progress': 10})}\n\n"

            file_bytes = file.read()

            if len(file_bytes) > 10 * 1024 * 1024:
                yield f"data: {json.dumps({'error': 'Файл больше 10 МБ'})}\n\n"
                return

            yield f"data: {json.dumps({'stage': 'Извлекаю текст...', 'progress': 30})}\n\n"

            resume_text = extract_text_from_pdf(file_bytes)

            if not resume_text or len(resume_text.split()) < 50:
                yield f"data: {json.dumps({'error': 'Не удалось извлечь текст'})}\n\n"
                return

            yield f"data: {json.dumps({'stage': 'Анализирую AI... 30-60 секунд', 'progress': 50})}\n\n"

            web_user_id = int(datetime.now().timestamp() * 1000000)
            ensure_user_exists_for_web(web_user_id)

            result = analyze_part(resume_text, "full_report", timeout=90)
            data = extract_json(result)

            if not data:
                yield f"data: {json.dumps({'error': 'Ошибка анализа'})}\n\n"
                return

            yield f"data: {json.dumps({'stage': 'Сохраняю отчёт...', 'progress': 80})}\n\n"

            save_analysis(
                web_user_id,
                resume_text,
                data.get('ats_score', 0),
                data.get('overall_score', 0),
                "web_upload"
            )

            report_id = str(uuid.uuid4())
            report_cache[report_id] = {
                'type': 'full',
                'user_id': web_user_id,
                'date': datetime.now().strftime('%d.%m.%Y %H:%M'),
                'overall': data.get('overall_score', 0),
                'ats': data.get('ats_score', 0),
                'keywords': data.get('keywords', []),
                'headlines': data.get('headlines', []),
                'critical_fixes': data.get('critical_fixes', []),
                'metrics_fixes': data.get('metrics_fixes', []),
                'style_fixes': data.get('style_fixes', []),
                'hh_rec': data.get('hh_recommendations', ''),
                'match_vac': data.get('match_vacancies', []),
                'verdict': data.get('verdict', '')
            }

            resume_cache[web_user_id] = resume_text

            yield f"data: {json.dumps({'stage': 'Готово!', 'progress': 100, 'redirect': f'/report/{report_id}'})}\n\n"

        except Exception as e:
            logger.error(f"Stream error: {e}", exc_info=True)
            yield f"data: {json.dumps({'error': str(e)[:100]})}\n\n"

    return Response(generate(), mimetype='text/event-stream')