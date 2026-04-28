import os
import uuid
import io
import csv
import re
import json
import requests as req
from datetime import datetime, timedelta
from flask import request, render_template_string, Response
import pdfplumber

from config import TELEGRAM_TOKEN, ADMIN_IDS, logger
from database import save_user, save_analysis, get_user_history, get_last_analysis_text, get_all_users, get_db
from ai import analyze_part
from telegram_helpers import send_message, send_welcome_video, clean_markdown, extract_json
from templates import REPORT_HTML, MATCH_HTML, COVER_HTML, IMPROVED_HTML, ADMIN_HTML, ADMIN_USERS_HTML

# Caches
report_cache = {} 
resume_cache = {}

def extract_text_from_pdf(file_bytes):
    try:
        text = ""
        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            for i, page in enumerate(pdf.pages):
                page_text = page.extract_text()
                if page_text:
                    text += page_text + "\n"
                else:
                    logger.warning(f"PDF page {i+1} returned no text")
        
        # Очистка
        lines = text.split('\n')
        seen = set()
        unique_lines = []
        for line in lines:
            stripped = line.strip()
            if stripped and stripped not in seen:
                seen.add(stripped)
                unique_lines.append(line)
        text = '\n'.join(unique_lines)
        text = re.sub(r'\?(\s|$)', r'\1', text)
        text = re.sub(r':{2,}', ':', text)
        text = re.sub(r'\s+', ' ', text)
        text = text.strip()
        
        logger.info(f"PDF extracted: {len(text)} chars. Preview: {text[:200]}...")
        return text
    except Exception as e:
        logger.error(f"PDF error: {e}")
        return None

def show_start_menu(chat_id):
    if chat_id in ADMIN_IDS:
        kb = {
            "keyboard": [
                ["📄 Загрузить резюме"], 
                ["❓ Помощь", "🔐 Админ-панель"]
            ],
            "resize_keyboard": True
        }
    else:
        kb = {
            "keyboard": [
                ["📄 Загрузить резюме"], 
                ["❓ Помощь"]
            ],
            "resize_keyboard": True
        }
    send_message(chat_id, "👇 <b>Выберите действие:</b>", reply_markup=kb)
    welcome_text = (
        "🤖 <b>Добро пожаловать в ResumeEasy!</b>\n\n"
        "Я — ваш персональный ATS-эксперт. Загрузите резюме и получите:\n"
        "✅ Чек-лист правок с категориями\n"
        "✅ Автоматическое улучшение резюме\n"
        "✅ Сравнение версий и прогресс\n\n"
        "📤 <b>Отправьте PDF прямо сейчас</b> — первый разбор через 30 секунд."
    )
    send_welcome_video(chat_id, welcome_text)

def show_post_upload_menu(chat_id):
    kb = {
        "keyboard": [
            ["📊 Получить отчет"], 
            ["🎯 Сравнить с вакансией", "📝 Сопроводительное"], 
            ["📈 Моя история", "📄 Новое резюме"], 
            ["⬅️ Назад в меню"]
        ],
        "resize_keyboard": True
    }
    send_message(chat_id, "✅ <b>Резюме загружено!</b>\nНажми «Получить отчет» для полного анализа.", reply_markup=kb)

def register_routes(app):
    
    @app.route('/report/<report_id>')
    def view_report(report_id):
        data = report_cache.get(report_id)
        if not data:
            return "<h1 style='color:white;font-family:sans-serif;text-align:center;margin-top:50px'>Срок действия отчёта истёк 😢<br><small>Сгенерируйте новый в боте</small></h1>", 404
        if data.get('type') == 'full':
            return render_template_string(REPORT_HTML, **data, report_id=report_id)
        elif data.get('type') == 'match':
            return render_template_string(MATCH_HTML, **data)
        elif data.get('type') == 'cover':
            return render_template_string(COVER_HTML, **data)
        return "<h1>Unknown type</h1>", 404

    @app.route('/improved/<improved_id>')
    def view_improved(improved_id):
        data = report_cache.get(improved_id)
        if not data:
            return "<h1 style='color:white;font-family:sans-serif;text-align:center;margin-top:50px'>Срок действия истёк 😢<br><small>Сгенерируйте заново</small></h1>", 404
        return render_template_string(IMPROVED_HTML, **data, report_id=improved_id)

    @app.route('/api/improve', methods=['POST'])
    def api_improve():
        data = request.get_json()
        report_id = data.get('report_id')
        fixes = data.get('fixes', [])
        
        report = report_cache.get(report_id)
        user_id = None
        resume_text = None
        
        if report:
            user_id = report.get('user_id')
            resume_text = resume_cache.get(user_id)
        
        if not resume_text:
            try:
                conn = get_db()
                c = conn.cursor()
                c.execute("SELECT user_id, resume_text FROM analyses WHERE analysis_type='full_report' ORDER BY id DESC LIMIT 1")
                row = c.fetchone()
                conn.close()
                if row:
                    user_id = row[0]
                    resume_text = row[1]
                    if len(resume_text) < 1000 and user_id in resume_cache:
                        resume_text = resume_cache[user_id]
                    resume_cache[user_id] = resume_text
            except Exception as e:
                logger.error(f"DB lookup error: {e}")
        
        if not resume_text:
            return {"redirect": None, "error": "Не могу найти текст резюме."}
        
        logger.info(f"Improving resume, text length: {len(resume_text)} chars")
        
        fixes_text = "\n".join([f"- {f['title']}: {f['desc']}" for f in fixes])
        
        custom_prompt = f"""Улучши резюме по указанным правкам. Верни СТРОГО JSON:

{{
  "blocks": [
    {{"title": "Заголовок", "text": "ФИО: ...\\nТелефон: ...\\nEmail: ...\\nГород: ...\\nГражданство: ..."}},
    {{"title": "Желаемая должность", "text": "Операционный директор (СОО)"}},
    {{"title": "Опыт работы", "text": "Компания 1, должность, даты:\\n• достижение\\n• достижение\\n\\nКомпания 2, должность, даты:\\n• достижение"}},
    {{"title": "Образование", "text": "образование"}},
    {{"title": "Навыки", "text": "навык1, навык2, навык3"}},
    {{"title": "Обо мне", "text": "текст"}}
  ],
  "summary": "Краткий итог: что улучшено",
  "overall_score": 85,
  "ats_score": 90
}}

ПРАВИЛА:
- НЕ придумывай компании, вузы, имена, цифры. ТОЛЬКО из резюме.
- Контакты оставь БЕЗ изменений.
- Желаемая должность — ТОЛЬКО название должности (без зарплаты, типа занятости).
- Опыт работы разбей по компаниям: Компания, должность, даты → буллиты с достижениями.
- Навыки — через запятую, одной строкой.
- overall_score и ats_score поставь РЕАЛЬНЫЕ оценки (не 0/0).
- НЕ используй Markdown.

Правки:
{fixes_text}

ВСЁ РЕЗЮМЕ:
{resume_text}

JSON:"""
        
        result = analyze_part("", "", custom_prompt=custom_prompt, timeout=120)
        
        if not result:
            return {"redirect": None, "error": "AI не ответил."}
        
        d = extract_json(result)
        if not d or 'blocks' not in d:
            logger.error(f"Failed to parse: {result[:300]}")
            return {"redirect": None, "error": "Не удалось разобрать ответ."}
        
        improved_id = str(uuid.uuid4())
        report_cache[improved_id] = {
            'type': 'improved',
            'date': datetime.now().strftime('%d.%m.%Y %H:%M'),
            'blocks': d.get('blocks', []),
            'summary': d.get('summary', ''),
            'overall': d.get('overall_score', 0) or 85,
            'ats': d.get('ats_score', 0) or 90,
            'original_report_id': report_id,
            'user_id': user_id
        }
        
        try:
            if user_id:
                save_analysis(user_id, resume_text[:10000], 
                            d.get('ats_score', 0) or 90, d.get('overall_score', 0) or 85, "improved")
        except Exception as e:
            logger.error(f"Failed to save to DB: {e}")
        
        return {"redirect": f"/improved/{improved_id}"}

    @app.route('/admin')
    @app.route('/admin/')
    def admin_dashboard():
        conn = None
        try:
            import psycopg2.extras
            conn = get_db()
            c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            c.execute("SELECT COUNT(*) as cnt FROM users")
            total_users = c.fetchone()['cnt']
            c.execute("SELECT COUNT(*) as cnt FROM users WHERE join_date::date = CURRENT_DATE")
            new_today = c.fetchone()['cnt']
            c.execute("SELECT COUNT(*) as cnt FROM analyses")
            total_analyses = c.fetchone()['cnt']
            c.execute("SELECT COUNT(*) as cnt FROM users WHERE last_activity >= NOW() - INTERVAL '7 days'")
            active_week = c.fetchone()['cnt']
            c.execute('''SELECT u.user_id, u.username, u.first_name, u.last_activity,
                COUNT(a.id) as total, COALESCE(AVG(a.ats_score), 0) as avg_ats
                FROM users u LEFT JOIN analyses a ON u.user_id = a.user_id
                GROUP BY u.user_id ORDER BY u.last_activity DESC NULLS LAST LIMIT 20''')
            users = c.fetchall()
            chart_labels, chart_data = [], []
            for i in range(6, -1, -1):
                date = datetime.now() - timedelta(days=i)
                chart_labels.append(date.strftime('%d.%m'))
                c.execute("SELECT COUNT(*) as cnt FROM users WHERE join_date::date = %s", (date.strftime('%Y-%m-%d'),))
                chart_data.append(c.fetchone()['cnt'])
            conn.close()
            return render_template_string(ADMIN_HTML, now=datetime.now().strftime('%d.%m.%Y %H:%M'),
                total_users=total_users, new_today=new_today, total_analyses=total_analyses,
                active_week=active_week, users=users, chart_labels=chart_labels, chart_data=chart_data)
        except Exception as e:
            logger.error(f"Admin error: {e}")
            if conn: conn.close()
            return "<h1 style='color:white'>Admin error</h1>", 500

    @app.route('/admin/users')
    def admin_users():
        conn = None
        try:
            import psycopg2.extras
            conn = get_db()
            c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            c.execute('''SELECT u.user_id, u.username, u.first_name, u.join_date, u.last_activity,
                COUNT(a.id) as total, COALESCE(AVG(a.ats_score), 0) as avg_ats
                FROM users u LEFT JOIN analyses a ON u.user_id = a.user_id
                GROUP BY u.user_id ORDER BY u.last_activity DESC NULLS LAST''')
            users = c.fetchall()
            conn.close()
            return render_template_string(ADMIN_USERS_HTML, users=users, now=datetime.now())
        except Exception as e:
            logger.error(f"Admin users error: {e}")
            if conn: conn.close()
            return "<h1 style='color:white'>Error loading users</h1>", 500

    @app.route('/admin/export')
    def admin_export():
        conn = None
        try:
            conn = get_db()
            c = conn.cursor()
            c.execute('''SELECT u.user_id, u.username, u.first_name, u.join_date, u.last_activity,
                COUNT(a.id) as total, COALESCE(AVG(a.ats_score), 0) as avg_ats
                FROM users u LEFT JOIN analyses a ON u.user_id = a.user_id
                GROUP BY u.user_id ORDER BY u.last_activity DESC NULLS LAST''')
            rows = c.fetchall()
            conn.close()
            output = io.StringIO()
            writer = csv.writer(output)
            writer.writerow(['User ID', 'Username', 'First Name', 'Join Date', 'Last Activity', 'Analyses', 'Avg ATS'])
            writer.writerows(rows)
            return Response(output.getvalue(), mimetype="text/csv",
                headers={"Content-Disposition": f"attachment;filename=users_{datetime.now().strftime('%Y%m%d')}.csv"})
        except Exception as e:
            logger.error(f"Export error: {e}")
            if conn: conn.close()
            return "<h1 style='color:white'>Export error</h1>", 500

    @app.route('/webhook', methods=['POST'])
    def webhook():
        chat_id = None
        try:
            data = request.get_json()
            if not data or 'message' not in data:
                return 'ok', 200
            chat_id = data['message']['chat']['id']
            user = data['message']['from']
            save_user(chat_id, user.get('username','anon'), user.get('first_name',''))
            text = data['message'].get('text', '')
            
            if text in ['/start', '⬅️ Назад в меню']:
                show_start_menu(chat_id); return 'ok', 200
            if text == '❓ Помощь':
                send_message(chat_id, "📘 <b>Как пользоваться:</b>\n1. Загрузи PDF\n2. Нажми «Получить отчет»\n3. Отметь нужные правки\n4. Нажми «Сгенерировать»"); return 'ok', 200
            if text == '📈 Моя история':
                hist = get_user_history(chat_id, 5)
                if not hist: send_message(chat_id, "📭 Истории пока нет."); return 'ok', 200
                msg = "📈 <b>Твои анализы:</b>\n"
                for i, row in enumerate(hist, 1):
                    msg += f"{i}. {row['analysis_date'].strftime('%d.%m.%Y')} | ATS: {row['ats_score'] or '?'} | HR: {row['overall_score'] or '?'}\n"
                send_message(chat_id, msg); return 'ok', 200
            if text == '🔐 Админ-панель':
                if chat_id not in ADMIN_IDS: send_message(chat_id, "🔐 Доступ запрещён"); return 'ok', 200
                domain = os.environ.get("RAILWAY_PUBLIC_DOMAIN") or request.host_url.rstrip('/')
                kb = {"inline_keyboard": [[{"text": "🔐 Открыть админ-панель", "url": f"{domain}/admin"}]]}
                send_message(chat_id, "📊 <b>Админ-панель готова!</b>", reply_markup=kb); return 'ok', 200
            if text.startswith('/admin_hist '):
                if chat_id not in ADMIN_IDS: return 'ok', 200
                target_id = text.split()[1]
                hist = get_user_history(int(target_id), 20)
                if not hist: send_message(chat_id, f"🔍 У пользователя {target_id} нет анализов."); return 'ok', 200
                msg = f"📋 История {target_id}\n"
                for row in hist: msg += f"📅 {row['analysis_date'].strftime('%d.%m.%Y')} | ATS: {row['ats_score']} | HR: {row['overall_score']}\n"
                send_message(chat_id, msg); return 'ok', 200
            if text in ['📄 Загрузить резюме', '📄 Новое резюме']:
                resume_cache[f"{chat_id}_mode"] = None
                send_message(chat_id, "📎 Отправь PDF (до 10 МБ)"); return 'ok', 200
            if 'document' in data['message']:
                doc = data['message']['document']
                if doc.get('file_size', 0) > 10*1024*1024: send_message(chat_id, "❌ Файл >10 МБ"); return 'ok', 200
                if doc.get('mime_type') != 'application/pdf': send_message(chat_id, "❌ Нужен PDF"); return 'ok', 200
                send_message(chat_id, "🔍 Извлекаю текст...")
                fid = doc['file_id']
                finfo = req.get(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getFile?file_id={fid}", timeout=30).json()
                if not finfo.get('ok'): send_message(chat_id, "❌ Ошибка файла"); return 'ok', 200
                rtext = extract_text_from_pdf(req.get(f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{finfo['result']['file_path']}", timeout=60).content)
                if not rtext or len(rtext.split()) < 50: send_message(chat_id, "❌ Текст не извлечён"); return 'ok', 200
                logger.info(f"PDF loaded for user {chat_id}: {len(rtext)} chars")
                resume_cache[chat_id] = rtext
                resume_cache[f"{chat_id}_mode"] = None
                show_post_upload_menu(chat_id); return 'ok', 200
            if text == '🎯 Сравнить с вакансией':
                if not resume_cache.get(chat_id): send_message(chat_id, "❌ Сначала загрузи резюме!"); return 'ok', 200
                resume_cache[f"{chat_id}_mode"] = "job_desc"
                send_message(chat_id, "📋 Скопируй текст вакансии и отправь сюда."); return 'ok', 200
            if resume_cache.get(f"{chat_id}_mode") == "job_desc":
                job_desc = text[:3000]
                resume_cache[f"{chat_id}_last_job"] = job_desc
                send_message(chat_id, "🔍 Сравниваю... ⏳")
                res = analyze_part(resume_cache[chat_id], "job_match", timeout=40, job_desc=job_desc)
                d = extract_json(res)
                if d and isinstance(d, dict):
                    report_id = str(uuid.uuid4())
                    report_cache[report_id] = {'type': 'match', 'date': datetime.now().strftime('%d.%m.%Y %H:%M'), 'match': d.get('match_percent', 0), 'missing': d.get('missing_skills', []), 'recs': d.get('recommendations', []), 'summary': d.get('summary', '')}
                    domain = os.environ.get("RAILWAY_PUBLIC_DOMAIN") or request.host_url.rstrip('/')
                    kb = {"inline_keyboard": [[{"text": "🌐 Открыть отчет", "url": f"{domain}/report/{report_id}"}]]}
                    send_message(chat_id, "✅ <b>Сравнение готово!</b>", reply_markup=kb)
                else: send_message(chat_id, "❌ Не удалось сравнить.")
                resume_cache[f"{chat_id}_mode"] = None; return 'ok', 200
            if text == '📝 Сопроводительное':
                if not resume_cache.get(chat_id): send_message(chat_id, "❌ Сначала загрузи резюме!"); return 'ok', 200
                saved_job = resume_cache.get(f"{chat_id}_last_job")
                if saved_job:
                    kb = {"keyboard": [["📋 Использовать прошлую вакансию"], ["🆕 Указать новую вакансию"], ["📝 Без вакансии (общее)"]], "resize_keyboard": True}
                    send_message(chat_id, "📝 <b>Сопроводительное письмо</b>", reply_markup=kb)
                else:
                    kb = {"keyboard": [["🆕 Указать вакансию"], ["📝 Без вакансии (общее)"]], "resize_keyboard": True}
                    send_message(chat_id, "📝 <b>Сопроводительное письмо</b>", reply_markup=kb)
                return 'ok', 200
            if text == '📋 Использовать прошлую вакансию':
                if not resume_cache.get(chat_id): send_message(chat_id, "❌ Сначала загрузи резюме!"); return 'ok', 200
                saved_job = resume_cache.get(f"{chat_id}_last_job")
                if not saved_job: send_message(chat_id, "❌ Нет сохранённой вакансии"); return 'ok', 200
                send_message(chat_id, "📝 Генерирую... ⏳")
                res = analyze_part(resume_cache[chat_id], "cover_letter", timeout=40, job_desc=saved_job)
                if res:
                    res = clean_markdown(res)
                    report_id = str(uuid.uuid4()); report_cache[report_id] = {'type': 'cover', 'letter': res}
                    domain = os.environ.get("RAILWAY_PUBLIC_DOMAIN") or request.host_url.rstrip('/')
                    kb = {"inline_keyboard": [[{"text": "🌐 Открыть письмо", "url": f"{domain}/report/{report_id}"}]]}
                    send_message(chat_id, "✅ <b>Письмо готово!</b>", reply_markup=kb)
                else: send_message(chat_id, "❌ Ошибка генерации")
                show_post_upload_menu(chat_id); return 'ok', 200
            if text in ['🆕 Указать новую вакансию', '🆕 Указать вакансию']:
                if not resume_cache.get(chat_id): send_message(chat_id, "❌ Сначала загрузи резюме!"); return 'ok', 200
                resume_cache[f"{chat_id}_mode"] = "cover_letter_job"
                send_message(chat_id, "📋 Отправьте текст вакансии:"); return 'ok', 200
            if text == '📝 Без вакансии (общее)':
                if not resume_cache.get(chat_id): send_message(chat_id, "❌ Сначала загрузи резюме!"); return 'ok', 200
                send_message(chat_id, "📝 Генерирую... ⏳")
                res = analyze_part(resume_cache[chat_id], "cover_letter", timeout=40, job_desc=None)
                if res:
                    res = clean_markdown(res)
                    report_id = str(uuid.uuid4()); report_cache[report_id] = {'type': 'cover', 'letter': res}
                    domain = os.environ.get("RAILWAY_PUBLIC_DOMAIN") or request.host_url.rstrip('/')
                    kb = {"inline_keyboard": [[{"text": "🌐 Открыть письмо", "url": f"{domain}/report/{report_id}"}]]}
                    send_message(chat_id, "✅ <b>Письмо готово!</b>", reply_markup=kb)
                else: send_message(chat_id, "❌ Ошибка генерации")
                show_post_upload_menu(chat_id); return 'ok', 200
            if resume_cache.get(f"{chat_id}_mode") == "cover_letter_job":
                job_desc = text[:3000]
                resume_cache[f"{chat_id}_last_job"] = job_desc
                send_message(chat_id, "📝 Генерирую... ⏳")
                res = analyze_part(resume_cache[chat_id], "cover_letter", timeout=40, job_desc=job_desc)
                if res:
                    res = clean_markdown(res)
                    report_id = str(uuid.uuid4()); report_cache[report_id] = {'type': 'cover', 'letter': res}
                    domain = os.environ.get("RAILWAY_PUBLIC_DOMAIN") or request.host_url.rstrip('/')
                    kb = {"inline_keyboard": [[{"text": "🌐 Открыть письмо", "url": f"{domain}/report/{report_id}"}]]}
                    send_message(chat_id, "✅ <b>Письмо готово!</b>", reply_markup=kb)
                else: send_message(chat_id, "❌ Ошибка генерации")
                resume_cache[f"{chat_id}_mode"] = None
                show_post_upload_menu(chat_id); return 'ok', 200
            if text == '📊 Получить отчет':
                rtext = resume_cache.get(chat_id)
                if not rtext: send_message(chat_id, "❌ Сначала загрузи резюме"); return 'ok', 200
                send_message(chat_id, "🧠 HR-эксперт анализирует... ⏳")
                logger.info(f"Starting full_report analysis for user {chat_id}, text length: {len(rtext)}")
                res = analyze_part(rtext, "full_report", timeout=90)
                d = extract_json(res)
                if not d: send_message(chat_id, "❌ Не удалось сформировать отчет."); return 'ok', 200
                logger.info(f"Report generated: ATS={d.get('ats_score')}, Overall={d.get('overall_score')}")
                report_id = str(uuid.uuid4())
                save_analysis(chat_id, rtext[:10000], d.get('ats_score', 0), d.get('overall_score', 0), "full_report")
                report_cache[report_id] = {
                    'type': 'full', 'user_id': chat_id,
                    'date': datetime.now().strftime('%d.%m.%Y %H:%M'),
                    'overall': d.get('overall_score', 0), 'ats': d.get('ats_score', 0),
                    'keywords': d.get('keywords', []), 'headlines': d.get('headlines', []),
                    'critical_fixes': d.get('critical_fixes', []),
                    'metrics_fixes': d.get('metrics_fixes', []),
                    'style_fixes': d.get('style_fixes', []),
                    'hh_rec': d.get('hh_recommendations', ''),
                    'match_vac': d.get('match_vacancies', []),
                    'verdict': d.get('verdict', '')
                }
                domain = os.environ.get("RAILWAY_PUBLIC_DOMAIN") or request.host_url.rstrip('/')
                kb = {"inline_keyboard": [[{"text": "🌐 Открыть полный отчет", "url": f"{domain}/report/{report_id}"}]]}
                send_message(chat_id, "✅ <b>Отчет готов!</b>\nОтметьте нужные правки и нажмите «Сгенерировать» в отчете.", reply_markup=kb)
                return 'ok', 200
            return 'ok', 200
        except Exception as e:
            logger.error(f"Crash: {e}", exc_info=True)
            if chat_id: send_message(chat_id, f"❌ Ошибка: {str(e)[:100]}")
            return 'error', 500
