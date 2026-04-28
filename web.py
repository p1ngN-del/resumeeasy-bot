import io
import uuid
import logging
from datetime import datetime
from flask import Blueprint, request, render_template_string, jsonify

from database import save_analysis
from ai import analyze_part
from telegram_helpers import extract_json
from handlers import extract_text_from_pdf, report_cache, resume_cache
from templates_landing import LANDING_HTML

logger = logging.getLogger(__name__)
web_bp = Blueprint('web', __name__)

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
        
        # Извлекаем текст
        resume_text = extract_text_from_pdf(file_bytes)
        if not resume_text or len(resume_text.split()) < 50:
            return jsonify({"error": "Не удалось извлечь текст из PDF. Попробуйте другой файл."}), 400
        
        logger.info(f"Web upload: extracted {len(resume_text)} chars")
        
        # Анализируем
        result = analyze_part(resume_text, "full_report", timeout=90)
        data = extract_json(result)
        
        if not data:
            return jsonify({"error": "Не удалось проанализировать резюме. Попробуйте позже."}), 500
        
        # Сохраняем
        web_user_id = hash(str(datetime.now().timestamp())) % 10000000
        save_analysis(web_user_id, resume_text, data.get('ats_score', 0), data.get('overall_score', 0), "web_upload")
        
        report_id = str(uuid.uuid4())
        report_cache[report_id] = {
            'type': 'full', 'user_id': web_user_id,
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
        logger.error(f"Web analyze error: {e}")
        return jsonify({"error": f"Ошибка сервера: {str(e)[:100]}"}), 500
