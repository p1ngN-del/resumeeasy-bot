#!/usr/bin/env python3
import os, io, logging, requests, sqlite3, re, json, time, uuid
from datetime import datetime
from flask import Flask, request, render_template_string
from PyPDF2 import PdfReader

# --- CONFIGURATION ---
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY")
ADMIN_IDS = set(map(int, os.environ.get("ADMIN_IDS", "0").split(",")))

if not TELEGRAM_TOKEN or not DEEPSEEK_API_KEY:
    raise ValueError("Missing TELEGRAM_TOKEN or DEEPSEEK_API_KEY")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

app = Flask(__name__)
DB_NAME = "resumeeasy.db"

# Caches
report_cache = {} 
resume_cache = {}

# --- DATABASE ---
def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY, username TEXT, first_name TEXT,
        join_date TEXT, last_activity TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS analyses (
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER,
        resume_text TEXT, ats_score INTEGER, overall_score INTEGER,
        analysis_type TEXT, analysis_date TEXT,
        FOREIGN KEY (user_id) REFERENCES users (user_id))''')
    conn.commit()
    conn.close()

def save_user(user_id, username, first_name):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''INSERT OR REPLACE INTO users
        (user_id, username, first_name, join_date, last_activity)
        VALUES (?, ?, ?, COALESCE((SELECT join_date FROM users WHERE user_id=?), ?), ?)''',
        (user_id, username, first_name, user_id, datetime.now().isoformat(), datetime.now().isoformat()))
    conn.commit()
    conn.close()

def save_analysis(user_id, resume_text, ats, overall, a_type="standard"):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''INSERT INTO analyses
        (user_id, resume_text, ats_score, overall_score, analysis_type, analysis_date)
        VALUES (?, ?, ?, ?, ?, ?)''',
        (user_id, resume_text[:500], ats, overall, a_type, datetime.now().isoformat()))
    conn.commit()
    conn.close()

def get_user_history(user_id, limit=5):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''SELECT analysis_date, ats_score, overall_score, analysis_type
        FROM analyses WHERE user_id=? ORDER BY id DESC LIMIT ?''', (user_id, limit))
    rows = c.fetchall()
    conn.close()
    return rows

def get_all_users(limit=10):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''SELECT u.user_id, u.username, u.first_name, u.join_date,
        COUNT(a.id) as total, AVG(a.ats_score) as avg_ats
        FROM users u LEFT JOIN analyses a ON u.user_id = a.user_id
        GROUP BY u.user_id ORDER BY u.last_activity DESC LIMIT ?''', (limit,))
    rows = c.fetchall()
    conn.close()
    return rows

# --- TELEGRAM HELPERS ---
def send_message(chat_id, text, reply_markup=None, parse_mode="HTML"):
    chunks = [text[i:i+4000] for i in range(0, len(text), 4000)]
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    for chunk in chunks:
        payload = {"chat_id": chat_id, "text": chunk, "parse_mode": parse_mode}
        if reply_markup and chunk == chunks[-1]:
            payload["reply_markup"] = json.dumps(reply_markup)
        try:
            requests.post(url, json=payload, timeout=30)
        except Exception as e:
            logger.error(f"Send error: {e}")

def send_welcome_video(chat_id, caption):
    """Отправляет приветственное видео с подписью"""
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendVideo"
    video_path = "welcome.mp4"
    
    # Проверяем, существует ли файл локально (на Railway он будет)
    if not os.path.exists(video_path):
        logger.warning("Welcome video not found, sending text only.")
        send_message(chat_id, caption)
        return

    try:
        with open(video_path, "rb") as video:
            files = {"video": video}
            data = {"chat_id": chat_id, "caption": caption, "parse_mode": "HTML"}
            requests.post(url, files=files, data=data, timeout=60)
    except Exception as e:
        logger.error(f"Video send error: {e}")
        # Если видео не загрузилось, отправим только текст
        send_message(chat_id, caption)

def extract_json(text):
    text = re.sub(r'```json\s*|\s*```', '', text).strip()
    try: return json.loads(text)
    except:
        m = re.search(r'\{.*\}', text, re.DOTALL)
        if m:
            try: return json.loads(m.group())
            except: pass
    return None

def extract_text_from_pdf(file_bytes):
    try:
        pdf = PdfReader(io.BytesIO(file_bytes))
        return "\n".join(p.extract_text() or "" for p in pdf.pages).strip()
    except Exception as e:
        logger.error(f"PDF error: {e}")
        return None

def get_level(score):
    try:
        s = float(score)
        if s >= 90: return "🏆 Эксперт"
        if s >= 75: return "⭐ Профи"
        if s >= 60: return "🚀 В процессе"
        return "🌱 Новичок"
    except: return "🌱 Новичок"

# --- AI ANALYSIS ---
def analyze_part(resume_text, part_name, timeout=60, custom_prompt=None, job_desc=None):
    url = "https://api.deepseek.com/v1/chat/completions"
    headers = {"Authorization": f"Bearer {DEEPSEEK_API_KEY}", "Content-Type": "application/json"}
    
    # --- PROMPTS ---
    prompts = {
        "full_report": f"""Ты — старший HR-рекрутер и эксперт по ATS с 10+ лет опыта в России.
Проанализируй резюме и верни СТРОГО JSON объект со следующей структурой:
{{
  "overall_score": 0-100,
  "ats_score": 0-100,
  "keywords": ["keyword1", "keyword2"],
  "headlines": ["var1", "var2", "var3"],
  "fixes": [{{"original": "text", "fixed": "text"}}],
  "hh_recommendations": "text",
  "match_vacancies": ["vac1", "vac2"],
  "verdict": "text"
}}

Критерии оценки:
1. Общая оценка: метрики, action-verbs, хронология, отсутствие воды.
2. ATS: чистый текст, ключевые слова, стандартные заголовки.
3. Fixes: минимум 6 улучшений формулировок с добавлением метрик.
4. Headlines: 3 варианта для hh.ru.

Резюме:
{resume_text[:4000]}""",
        
        "cover_letter": f"""Ты — старший HR-рекрутер. Напиши короткое, ударное сопроводительное письмо для hh.ru.
Требования:
- 5-10 предложений.
- Первое предложение: имя, должность, ключевой результат.
- 3-4 буллита с достижениями под вакансию.
- Живой язык, без штампов.
- В конце: контакты.
- НЕ пиши "Резюме прилагаю".

Резюме:
{resume_text[:3000]}

Вакансия:
{job_desc[:3000] if job_desc else 'Не указана (напиши универсальное письмо)'}"""
    }
    
    payload = {
        "model": "deepseek-chat", 
        "messages": [{"role": "user", "content": custom_prompt or prompts[part_name]}], 
        "temperature": 0.2, 
        "max_tokens": 4000
    }
    try:
        r = requests.post(url, headers=headers, json=payload, timeout=timeout)
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        logger.error(f"AI Error: {e}")
        return None

# --- MENUS ---
def show_start_menu(chat_id):
    kb = {
        "keyboard": [
            ["📄 Загрузить резюме"], 
            ["❓ Помощь", "🔐 Админ-панель"]
        ],
        "resize_keyboard": True
    }
    # Текст приветствия
    welcome_text = (
        "🤖 <b>Добро пожаловать в ResumeEasy!</b>\n\n"
        "Рынок труда в 2026 году изменился:\n"
        "🔹 80% компаний используют ATS-фильтры\n"
        "🔹 На 1 вакансию теперь откликаются 300+ кандидатов\n"
        "🔹 HR ищут не «опыт», а конкретные цифры и метрики\n\n"
        "Этот бот — ваш персональный ATS-эксперт. Он:\n"
        "✅ Проверит резюме на совместимость с системами отбора\n"
        "✅ Покажет, где вы теряете шансы на интервью\n"
        "✅ Даст готовые формулировки с ключевыми словами\n\n"
        "📤 <b>Загрузите PDF-резюме прямо сейчас</b> — и получите разбор за 30 секунд."
    )
    
    send_welcome_video(chat_id, welcome_text)
    # Отправляем меню отдельным сообщением, чтобы оно не перекрывало видео
    time.sleep(1) 
    send_message(chat_id, "👇 <b>Выберите действие:</b>", reply_markup=kb)

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

# --- WEB REPORT TEMPLATE (PROFESSIONAL DARK) ---
REPORT_HTML = """
<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Resume Expert Report</title>
    <style>
        body { background-color: #121212; color: #e0e0e0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; margin: 0; padding: 20px; line-height: 1.6; }
        .container { max-width: 800px; margin: 0 auto; background: #1e1e1e; padding: 30px; border-radius: 12px; box-shadow: 0 4px 20px rgba(0,0,0,0.5); }
        h1 { color: #ffffff; border-bottom: 2px solid #333; padding-bottom: 15px; margin-top: 0; font-size: 24px; }
        h2 { color: #bb86fc; margin-top: 30px; font-size: 18px; border-left: 4px solid #bb86fc; padding-left: 10px; }
        .score-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 15px; margin-bottom: 20px; }
        .score-card { background: #2c2c2c; padding: 15px; border-radius: 8px; text-align: center; }
        .score-val { font-size: 32px; font-weight: bold; color: #03dac6; }
        .score-label { font-size: 14px; color: #aaa; margin-top: 5px; }
        .tag { display: inline-block; background: #333; padding: 4px 8px; border-radius: 4px; margin: 2px; font-size: 12px; color: #03dac6; }
        .fix-item { background: #252525; padding: 10px; margin-bottom: 8px; border-radius: 6px; border-left: 3px solid #cf6679; }
        .fix-old { color: #cf6679; font-size: 13px; text-decoration: line-through; margin-bottom: 4px; }
        .fix-new { color: #03dac6; font-size: 14px; }
        .verbatim { white-space: pre-wrap; background: #252525; padding: 15px; border-radius: 6px; font-size: 14px; }
        .footer { margin-top: 40px; text-align: center; font-size: 12px; color: #666; }
    </style>
</head>
<body>
    <div class="container">
        <h1>📊 Expert Resume Analysis</h1>
        <p style="color: #888">Generated on {{ date }}</p>

        <div class="score-grid">
            <div class="score-card">
                <div class="score-val">{{ overall }}/100</div>
                <div class="score-label">Общая оценка HR</div>
            </div>
            <div class="score-card">
                <div class="score-val" style="color: #bb86fc">{{ ats }}/100</div>
                <div class="score-label">ATS Score (hh.ru)</div>
            </div>
        </div>

        <h2>🎯 Варианты заголовка для hh.ru</h2>
        <div class="verbatim">
        {% for h in headlines %}• {{ h }}<br>{% endfor %}
        </div>

        <h2>🔑 Ключевые слова</h2>
        <div>
        {% for k in keywords %}<span class="tag">{{ k }}</span>{% endfor %}
        </div>

        <h2>🛠 Точечные правки (Было → Стало)</h2>
        {% for fix in fixes %}
        <div class="fix-item">
            <div class="fix-old">{{ fix.original }}</div>
            <div class="fix-new">{{ fix.fixed }}</div>
        </div>
        {% endfor %}

        <h2>💡 Рекомендации по hh.ru</h2>
        <div class="verbatim">{{ hh_rec }}</div>

        <h2>📈 Подходящие вакансии</h2>
        <div class="verbatim">
        {% for v in match_vac %}• {{ v }}<br>{% endfor %}
        </div>

        <h2>🎤 Финальный вердикт</h2>
        <div class="verbatim">{{ verdict }}</div>

        <div class="footer">
            Powered by ResumeEasy Bot
        </div>
    </div>
</body>
</html>
"""

# --- ROUTES ---

@app.route('/report/<report_id>')
def view_report(report_id):
    data = report_cache.get(report_id)
    if not 
        return "<h1 style='color:white'>Report expired</h1>", 404
    
    return render_template_string(REPORT_HTML, **data)

@app.route('/webhook', methods=['POST'])
def webhook():
    chat_id = None
    try:
        data = request.get_json()
        if not data or 'message' not in 
            return 'ok', 200
        
        chat_id = data['message']['chat']['id']
        user = data['message']['from']
        save_user(chat_id, user.get('username','anon'), user.get('first_name',''))
        
        text = data['message'].get('text', '')
        
        # --- COMMANDS ---
        if text in ['/start', '⬅️ Назад в меню']:
            show_start_menu(chat_id)
            return 'ok', 200

        if text == '❓ Помощь':
            send_message(chat_id, "📘 <b>Как пользоваться:</b>\n1. Загрузи PDF\n2. Нажми «Получить отчет» для глубокого анализа.")
            return 'ok', 200

        if text == '📈 Моя история':
            hist = get_user_history(chat_id, 5)
            if not hist:
                send_message(chat_id, "📭 Истории пока нет.")
                return 'ok', 200
            msg = "📈 <b>Твои анализы:</b>\n"
            for i, (date, ats, ov, typ) in enumerate(hist, 1):
                msg += f"{i}. {date[:10]} | ATS: {ats or '?'} | HR: {ov or '?'}\n"
            send_message(chat_id, msg)
            return 'ok', 200

        if text == '🔐 Админ-панель':
            if chat_id not in ADMIN_IDS:
                send_message(chat_id, "🔐 Доступ запрещён")
                return 'ok', 200
            users = get_all_users(10)
            msg = "📊 <b>Панель управления</b>\n"
            for u_id, u_name, u_fn, j_date, total, avg_ats in users:
                avg_val = avg_ats if avg_ats else 0
                msg += f"• {u_fn or u_name} | Анализов: {total} | Ср. ATS: {avg_val:.0f}\n"
            send_message(chat_id, msg)
            return 'ok', 200

        if text.startswith('/admin_hist '):
            if chat_id not in ADMIN_IDS: return 'ok', 200
            target_id = text.split()[1]
            hist = get_user_history(int(target_id), 5)
            if not hist:
                send_message(chat_id, f"🔍 У пользователя {target_id} нет анализов.")
                return 'ok', 200
            msg = f"📋 История {target_id}\n"
            for date, ats, ov, typ in hist:
                msg += f"📅 {date[:10]} | ATS: {ats} | HR: {ov}\n"
            send_message(chat_id, msg)
            return 'ok', 200

        # --- FILE UPLOAD ---
        if text in ['📄 Загрузить резюме', '📄 Новое резюме']:
            resume_cache[f"{chat_id}_mode"] = None
            send_message(chat_id, "📎 Отправь PDF (до 10 МБ)")
            return 'ok', 200

        if 'document' in data['message']:
            doc = data['message']['document']
            if doc.get('file_size', 0) > 10*1024*1024:
                send_message(chat_id, "❌ Файл >10 МБ")
                return 'ok', 200
            if doc.get('mime_type') != 'application/pdf':
                send_message(chat_id, "❌ Нужен PDF")
                return 'ok', 200
            
            send_message(chat_id, "🔍 Извлекаю текст...")
            fid = doc['file_id']
            finfo = requests.get(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getFile?file_id={fid}", timeout=30).json()
            if not finfo.get('ok'):
                send_message(chat_id, "❌ Ошибка файла")
                return 'ok', 200
            
            rtext = extract_text_from_pdf(requests.get(f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{finfo['result']['file_path']}", timeout=60).content)
            if not rtext or len(rtext.split()) < 50:
                send_message(chat_id, "❌ Текст не извлечён")
                return 'ok', 200
            
            resume_cache[chat_id] = rtext
            resume_cache[f"{chat_id}_mode"] = None
            show_post_upload_menu(chat_id)
            return 'ok', 200

        # --- JOB COMPARISON ---
        if text == '🎯 Сравнить с вакансией':
            if not resume_cache.get(chat_id):
                send_message(chat_id, "❌ Сначала загрузи резюме!")
                return 'ok', 200
            resume_cache[f"{chat_id}_mode"] = "job_desc"
            send_message(chat_id, "📋 Скопируй текст вакансии и отправь сюда.")
            return 'ok', 200

        if resume_cache.get(f"{chat_id}_mode") == "job_desc":
            job_desc = text[:3000]
            rtext = resume_cache[chat_id]
            send_message(chat_id, "🔍 Сравниваю с вакансией... ⏳")
            
            # FIXED: Double curly braces for JSON inside f-string
            prompt = f"""Сравни резюме с вакансией. Верни JSON:
{{"match_percent": 0-100, "missing_skills": ["skill1"], "recommendations": ["rec1"]}}
Резюме:
{rtext[:2000]}
Вакансия:
{job_desc}"""
            res = analyze_part(rtext, "custom", custom_prompt=prompt, timeout=40)
            d = extract_json(res)
            if d and isinstance(d, dict):
                out = (f"🎯 <b>СОВПАДЕНИЕ</b>\n"
                       f"📊 {d.get('match_percent','?')}/100\n"
                       f"❌ <b>Не хватает</b>:\n" + "\n".join(f"• {s}" for s in d.get('missing_skills', [])) + "\n"
                       f"💡 <b>Совет</b>:\n" + "\n".join(f"• {r}" for r in d.get('recommendations', [])))
            else:
                out = "❌ Не удалось сравнить. Попробуй еще раз."
            send_message(chat_id, out)
            resume_cache[f"{chat_id}_mode"] = None
            return 'ok', 200

        # --- COVER LETTER GENERATION ---
        if text == '📝 Сопроводительное':
            if not resume_cache.get(chat_id):
                send_message(chat_id, "❌ Сначала загрузи резюме!")
                return 'ok', 200
            
            send_message(chat_id, "📝 Генерирую сопроводительное письмо... ⏳")
            rtext = resume_cache[chat_id]
            res = analyze_part(rtext, "cover_letter", timeout=40)
            if res:
                send_message(chat_id, f"<b>Ваше сопроводительное письмо:</b>\n\n{res}")
            else:
                send_message(chat_id, "❌ Ошибка генерации")
            return 'ok', 200

        # --- FULL REPORT GENERATION ---
        if text == '📊 Получить отчет':
            rtext = resume_cache.get(chat_id)
            if not rtext:
                send_message(chat_id, "❌ Сначала загрузи резюме")
                return 'ok', 200
            
            send_message(chat_id, "🧠 HR-эксперт анализирует резюме... Это займет около минуты ⏳")
            
            res = analyze_part(rtext, "full_report", timeout=90)
            d = extract_json(res)
            
            if not d:
                send_message(chat_id, "❌ Не удалось сформировать отчет. Попробуйте позже.")
                return 'ok', 200

            # Save to DB
            save_analysis(chat_id, rtext, d.get('ats_score', 0), d.get('overall_score', 0), "full_report")
            
            # Prepare Data for Web
            report_id = str(uuid.uuid4())
            report_data = {
                'date': datetime.now().strftime('%d.%m.%Y %H:%M'),
                'overall': d.get('overall_score', 0),
                'ats': d.get('ats_score', 0),
                'keywords': d.get('keywords', []),
                'headlines': d.get('headlines', []),
                'fixes': d.get('fixes', []),
                'hh_rec': d.get('hh_recommendations', ''),
                'match_vac': d.get('match_vacancies', []),
                'verdict': d.get('verdict', '')
            }
            report_cache[report_id] = report_data
            
            # Get Public URL
            domain = os.environ.get("RAILWAY_PUBLIC_DOMAIN") or request.host_url.rstrip('/')
            report_url = f"{domain}/report/{report_id}"
            
            kb = {"inline_keyboard": [[{"text": "🌐 Открыть полный отчет", "url": report_url}]]}
            send_message(chat_id, f"✅ <b>Отчет готов!</b>\nНажми кнопку ниже, чтобы увидеть детальный разбор от HR-эксперта.", reply_markup=kb)
            return 'ok', 200

        return 'ok', 200

    except Exception as e:
        logger.error(f"Crash: {e}", exc_info=True)
        if chat_id: send_message(chat_id, f"❌ Ошибка: {str(e)[:100]}")
        return 'error', 500

@app.route('/', methods=['GET','HEAD'])
def index(): return '✅ Online', 200

@app.route('/health')
def health(): return {"status":"ok"}, 200

if __name__ != "__main__":
    init_db()
    logger.info("🚀 Started")
