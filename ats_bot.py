#!/usr/bin/env python3
import os, io, logging, requests, sqlite3, re, json, time, uuid
from datetime import datetime
from flask import Flask, request, jsonify, render_template_string
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

# In-memory storage for reports and resumes (for Railway ephemeral disk safety during session)
# Note: For production with multiple workers, use Redis. For single worker Railway, dict is fine.
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

def get_score_emoji(score):
    try:
        s = float(score)
        if s >= 90: return "🟢"
        if s >= 70: return "🟡"
        if s >= 50: return "🟠"
        return "🔴"
    except: return "⚪"

# --- AI ANALYSIS ---
def analyze_part(resume_text, part_name, timeout=45, custom_prompt=None):
    url = "https://api.deepseek.com/v1/chat/completions"
    headers = {"Authorization": f"Bearer {DEEPSEEK_API_KEY}", "Content-Type": "application/json"}
    
    prompts = {
        "ats_score": f"""Оцени резюме по 5 критериям (0-100 каждый):
1. Контакты 2. Структура 3. Ключевые слова 4. Достижения с цифрами 5. Формат
ВЕРНИ ТОЛЬКО JSON: {{"contacts": N, "structure": N, "keywords": N, "achievements": N, "format": N, "overall": N}}
Резюме:
{resume_text[:4000]}""",
        "overall_score": f"Оцени резюме 0-100. ТОЛЬКО число.
Резюме:
{resume_text[:4000]}",
        "strengths": f"5-7 сильных сторон. ✅ в начале. БЕЗ *, #, HTML.
Резюме:
{resume_text[:4000]}",
        "weaknesses": f"5-7 слабых мест. ⚠️ в начале. БЕЗ *, #, HTML.
Резюме:
{resume_text[:4000]}",
        "recommendations": f"5 советов в формате:
❌ Проблема:
✅ Решение:
💡 Пример:
БЕЗ *, #, HTML.
Резюме:
{resume_text[:4000]}",
        "keywords": f"8-12 ключевых слов через запятую. ТОЛЬКО слова.
Резюме:
{resume_text[:4000]}",
        "final_verdict": f"""Дай чёткий финальный вердикт по резюме.
ОТВЕТЬ СТРОГО ПО ФОРМАТУ:
🎯 ГОТОВНОСТЬ К РАССЫЛКЕ: [Да/Нет/Частично]
❌ КРИТИЧЕСКИЕ ОШИБКИ (максимум 3):
1. [ошибка]
2. [ошибка]
3. [ошибка]
📈 ПРОГНОЗ КОНВЕРСИИ: [число]%
💡 ГЛАВНАЯ РЕКОМЕНДАЦИЯ: [одна конкретная фраза]
Без *, #, HTML. Только обычный текст с эмодзи.
Резюме:
{resume_text[:4000]}""",
        "rewrite": f"Перепиши резюме идеально. Только текст. Цифры, глаголы действия. Без *, #, HTML.
Оригинал:
{resume_text[:4000]}"
    }
    
    payload = {
        "model": "deepseek-chat", 
        "messages": [{"role": "user", "content": custom_prompt or prompts[part_name]}], 
        "temperature": 0, 
        "max_tokens": 3000
    }
    try:
        r = requests.post(url, headers=headers, json=payload, timeout=timeout)
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        logger.error(f"AI Error: {e}")
        return "⏳ Попробуй через минуту"

# --- MENUS ---
def show_main_menu(chat_id):
    kb = {
        "keyboard": [
            ["📄 Загрузить резюме"], 
            ["🎯 Сравнить с вакансией", "📝 Сопроводительное"], 
            ["📈 Моя история", "❓ Помощь"], 
            ["🔐 Админ-панель"]
        ],
        "resize_keyboard": True
    }
    send_message(chat_id, "👋 <b>ResumeEasy Bot</b>\n📊 ATS-анализ, сравнение и генерация документов", reply_markup=kb)

def show_analysis_menu(chat_id):
    kb = {
        "keyboard": [
            ["🚀 Полный разбор", "🤖 ATS-рубрика"], 
            ["💪 Сильные стороны", "⚠️ Слабые стороны"], 
            ["🔑 Ключевые слова", "💡 Советы (Было→Стало)"], 
            ["🎯 Вердикт", "✨ Переписать резюме"], 
            ["🌐 Открыть отчет", "📄 Новое резюме"], 
            ["⬅️ Назад в меню"]
        ],
        "resize_keyboard": True
    }
    send_message(chat_id, "✅ <b>Резюме загружено!</b>\n🎯 Выбери анализ:", reply_markup=kb)

# --- WEB REPORT TEMPLATE (CYBERPUNK STYLE) ---
REPORT_HTML = """
<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Resume Analysis Report</title>
    <style>
        :root {
            --bg-color: #0d0d12;
            --card-bg: #16161e;
            --accent: #00f3ff;
            --accent-dim: #00f3ff33;
            --text-main: #e0e0e0;
            --text-dim: #888;
            --success: #00ff9d;
            --warning: #ffbd00;
            --danger: #ff0055;
        }
        body {
            background-color: var(--bg-color);
            color: var(--text-main);
            font-family: 'Courier New', Courier, monospace;
            margin: 0;
            padding: 20px;
            line-height: 1.6;
        }
        .container {
            max-width: 800px;
            margin: 0 auto;
            border: 1px solid var(--accent-dim);
            padding: 30px;
            box-shadow: 0 0 20px var(--accent-dim);
            border-radius: 8px;
            position: relative;
            overflow: hidden;
        }
        .container::before {
            content: "";
            position: absolute;
            top: 0; left: 0; width: 100%; height: 4px;
            background: linear-gradient(90deg, var(--accent), var(--danger));
        }
        h1 {
            color: var(--accent);
            text-transform: uppercase;
            letter-spacing: 2px;
            border-bottom: 1px solid var(--accent-dim);
            padding-bottom: 10px;
            font-size: 24px;
        }
        h2 {
            color: var(--success);
            font-size: 18px;
            margin-top: 30px;
            display: flex;
            align-items: center;
        }
        h2::before {
            content: ">>";
            margin-right: 10px;
            color: var(--accent);
        }
        .score-box {
            display: flex;
            justify-content: space-between;
            align-items: center;
            background: var(--card-bg);
            padding: 15px;
            margin: 10px 0;
            border-left: 4px solid var(--accent);
        }
        .score-val {
            font-size: 24px;
            font-weight: bold;
            color: var(--accent);
        }
        .progress-bar {
            width: 100%;
            height: 6px;
            background: #333;
            margin-top: 5px;
            border-radius: 3px;
        }
        .progress-fill {
            height: 100%;
            background: var(--accent);
            box-shadow: 0 0 10px var(--accent);
        }
        .list-item {
            background: rgba(255,255,255,0.03);
            padding: 10px;
            margin-bottom: 8px;
            border-radius: 4px;
        }
        .footer {
            margin-top: 40px;
            text-align: center;
            font-size: 12px;
            color: var(--text-dim);
            border-top: 1px solid #333;
            padding-top: 20px;
        }
        .btn {
            display: inline-block;
            background: var(--accent);
            color: #000;
            padding: 10px 20px;
            text-decoration: none;
            font-weight: bold;
            margin-top: 20px;
            border-radius: 4px;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>📊 Resume Analysis Report</h1>
        <p style="color: var(--text-dim)">Generated by ResumeEasy Bot | {{ date }}</p>

        <div class="score-box">
            <div>
                <div>ATS SCORE</div>
                <div class="progress-bar"><div class="progress-fill" style="width: {{ ats }}%"></div></div>
            </div>
            <div class="score-val">{{ ats }}/100</div>
        </div>

        <div class="score-box" style="border-left-color: var(--success)">
            <div>
                <div>OVERALL MATCH</div>
                <div class="progress-bar"><div class="progress-fill" style="width: {{ overall }}%; background: var(--success)"></div></div>
            </div>
            <div class="score-val" style="color: var(--success)">{{ overall }}/100</div>
        </div>

        <h2>Strengths</h2>
        {% for item in strengths %}
        <div class="list-item">✅ {{ item }}</div>
        {% endfor %}

        <h2>Weaknesses</h2>
        {% for item in weaknesses %}
        <div class="list-item" style="border-left: 2px solid var(--danger)">⚠️ {{ item }}</div>
        {% endfor %}

        <h2>Recommendations</h2>
        {% for item in recommendations %}
        <div class="list-item">💡 {{ item }}</div>
        {% endfor %}

        <h2>Keywords Detected</h2>
        <p style="color: var(--accent)">{{ keywords }}</p>

        <div class="footer">
            <p>ResumeEasy Bot v2.0</p>
            <a href="https://t.me/ResumeEasyBot" class="btn">Back to Telegram</a>
        </div>
    </div>
</body>
</html>
"""

# --- ROUTES ---

@app.route('/report/<report_id>')
def view_report(report_id):
    data = report_cache.get(report_id)
    if not data:
        return "<h1 style='color:red'>Report expired or not found</h1>", 404
    
    # Simple parsing of lists from text strings if they are newlines
    def parse_list(text):
        if not text: return []
        return [line.strip() for line in text.split('\n') if line.strip()]

    return render_template_string(REPORT_HTML, 
        date=data.get('date', ''),
        ats=data.get('ats', 0),
        overall=data.get('overall', 0),
        strengths=parse_list(data.get('strengths', '')),
        weaknesses=parse_list(data.get('weaknesses', '')),
        recommendations=parse_list(data.get('recommendations', '')),
        keywords=data.get('keywords', '')
    )

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
        
        # --- COMMANDS ---
        if text in ['/start', '⬅️ Назад в меню']:
            show_main_menu(chat_id)
            return 'ok', 200

        if text == '❓ Помощь':
            send_message(chat_id, "📘 <b>Как пользоваться:</b>\n1. Загрузи PDF\n2. Выбери анализ или генерацию документов")
            return 'ok', 200

        if text == '📈 Моя история':
            hist = get_user_history(chat_id, 5)
            if not hist:
                send_message(chat_id, "📭 Истории пока нет. Загрузи резюме!")
                return 'ok', 200
            msg = "📈 <b>Твои анализы:</b>\n"
            for i, (date, ats, ov, typ) in enumerate(hist, 1):
                msg += f"{i}. {date[:10]} | ATS: {ats or '?'} | Общая: {ov or '?'}\n"
            msg += f"\n🏆 Уровень: {get_level(hist[0][2] if hist[0][2] else 0)}"
            send_message(chat_id, msg)
            return 'ok', 200

        if text == '🔐 Админ-панель':
            if chat_id not in ADMIN_IDS:
                send_message(chat_id, "🔐 Доступ запрещён")
                return 'ok', 200
            users = get_all_users(10)
            msg = "📊 <b>Панель управления</b>\n👥 Пользователи:\n"
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
            msg = f"📋 История пользователя {target_id}\n"
            for date, ats, ov, typ in hist:
                msg += f"📅 {date[:10]} | ATS: {ats} | Общая: {ov}\n"
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
            show_analysis_menu(chat_id)
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
            send_message(chat_id, "🔍 Сравниваю... ⏳")
            prompt = f"""Сравни резюме с вакансией. ВЕРНИ JSON:
{{"match_percent": 0-100, "missing_skills": ["skill1"], "critical_gap": "gap", "recommendations": ["rec1"]}}
Резюме:
{rtext[:2000]}
Вакансия:
{job_desc}"""
            res = analyze_part("", "custom", custom_prompt=prompt, timeout=40)
            d = extract_json(res)
            if d and isinstance(d, dict):
                out = (f"🎯 <b>СОВПАДЕНИЕ</b>\n"
                       f"📊 {d.get('match_percent','?')}/100 {get_score_emoji(d.get('match_percent',0))}\n"
                       f"❌ <b>Не хватает</b>:\n" + "\n".join(f"• {s}" for s in d.get('missing_skills', [])) + "\n"
                       f"💡 <b>Что добавить</b>:\n" + "\n".join(f"• {r}" for r in d.get('recommendations', [])))
            else:
                out = f"🎯 Анализ: {res}"
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
            prompt = f"""Напиши профессиональное сопроводительное письмо на основе этого резюме.
Текст должен быть вежливым, структурированным, с акцентом на ключевые достижения и навыки.
Отвечай строго в формате обычного текста. БЕЗ *, #, HTML, markdown.
Резюме:
{rtext[:3000]}"""
            cover = analyze_part(rtext, "custom", custom_prompt=prompt, timeout=35)
            send_message(chat_id, f"<b>Ваше сопроводительное письмо:</b>\n\n{cover}")
            return 'ok', 200

        # --- WEB REPORT GENERATION ---
        if text == '🌐 Открыть отчет':
            rtext = resume_cache.get(chat_id)
            if not rtext:
                send_message(chat_id, "❌ Сначала загрузи резюме")
                return 'ok', 200
            
            send_message(chat_id, "🎨 Создаю отчет... ⏳")
            
            # Parallel-ish calls for speed
            ats_r = analyze_part(rtext, "ats_score", timeout=30)
            ov_r = analyze_part(rtext, "overall_score", timeout=20)
            str_r = analyze_part(rtext, "strengths", timeout=30)
            weak_r = analyze_part(rtext, "weaknesses", timeout=30)
            key_r = analyze_part(rtext, "keywords", timeout=20)
            rec_r = analyze_part(rtext, "recommendations", timeout=30)
            
            d_ats = extract_json(ats_r)
            ats_val = d_ats.get('overall', 0) if d_ats else 0
            ov_val = int(ov_r) if ov_r.isdigit() else 0
            
            # Save to DB
            save_analysis(chat_id, rtext, ats_val, ov_val, "web_report")
            
            # Prepare Data for Web
            report_id = str(uuid.uuid4())
            report_data = {
                'date': datetime.now().strftime('%d.%m.%Y %H:%M'),
                'ats': ats_val,
                'overall': ov_val,
                'strengths': str_r,
                'weaknesses': weak_r,
                'keywords': key_r,
                'recommendations': rec_r
            }
            report_cache[report_id] = report_data
            
            # Get Public URL (Railway provides DOMAIN env var, or fallback)
            domain = os.environ.get("RAILWAY_PUBLIC_DOMAIN") or request.host_url.rstrip('/')
            report_url = f"{domain}/report/{report_id}"
            
            kb = {"inline_keyboard": [[{"text": "🌐 Открыть отчет", "url": report_url}]]}
            send_message(chat_id, f"✅ <b>Отчет готов!</b>\nНажми кнопку ниже, чтобы увидеть красивый веб-интерфейс.", reply_markup=kb)
            return 'ok', 200

        # --- STANDARD ANALYSIS BUTTONS ---
        PART_MAP = {
            '🤖 ATS-рубрика': 'ats_score', 
            '💪 Сильные стороны': 'strengths', 
            '⚠️ Слабые стороны': 'weaknesses', 
            '🔑 Ключевые слова': 'keywords', 
            '💡 Советы (Было→Стало)': 'recommendations', 
            '🎯 Вердикт': 'final_verdict', 
            '✨ Переписать резюме': 'rewrite'
        }
        
        if text in PART_MAP:
            rtext = resume_cache.get(chat_id)
            if not rtext:
                show_main_menu(chat_id)
                send_message(chat_id, "❌ Сессия сброшена")
                return 'ok', 200
            
            send_message(chat_id, "⏳ Анализирую...")
            res = analyze_part(rtext, PART_MAP[text])
            
            if PART_MAP[text] in ['ats_score', 'final_verdict']:
                try:
                    d = extract_json(res) if PART_MAP[text]=='ats_score' else None
                    ats = d.get('overall', 0) if d else 0
                    save_analysis(chat_id, rtext, ats, 0, PART_MAP[text])
                except: pass
                
            if text == '🤖 ATS-рубрика':
                d = extract_json(res)
                if d and isinstance(d, dict):
                    out = (f"🤖 <b>ATS-РУБРИКА</b>\n"
                           f"📞 Контакты: {d.get('contacts','?')} | 📐 Структура: {d.get('structure','?')}\n"
                           f"🔑 Ключевые: {d.get('keywords','?')} | 📊 Достижения: {d.get('achievements','?')}\n"
                           f"📝 Формат: {d.get('format','?')} | 🎯 <b>ИТОГО: {d.get('overall','?')}/100</b> {get_level(d.get('overall',0))}")
                else: out = f"🤖 ATS: {res}"
            else:
                out = res
            send_message(chat_id, out)
            return 'ok', 200

        if text == '🚀 Полный разбор':
            rtext = resume_cache.get(chat_id)
            if not rtext: return 'ok', 200
            send_message(chat_id, "🚀 <b>Полный разбор</b>\n⏳ Делаю по шагам...")
            
            ats_r = analyze_part(rtext, "ats_score", timeout=30)
            send_message(chat_id, "📊 Общая оценка...")
            ov_r = analyze_part(rtext, "overall_score", timeout=20)
            send_message(chat_id, "💪 Сильные стороны...")
            str_r = analyze_part(rtext, "strengths", timeout=30)
            send_message(chat_id, "⚠️ Слабые места...")
            weak_r = analyze_part(rtext, "weaknesses", timeout=30)
            send_message(chat_id, "💡 Советы...")
            rec_r = analyze_part(rtext, "recommendations", timeout=30)
            
            d = extract_json(ats_r)
            ats_val = d.get('overall', 0) if d and isinstance(d, dict) else 0
            ov_val = int(ov_r) if ov_r.isdigit() else 0
            save_analysis(chat_id, rtext, ats_val, ov_val, "full_breakdown")
            
            ats_block = (f"🤖 <b>ATS</b>\n"
                         f"📞 {d.get('contacts','?')} | 📐 {d.get('structure','?')} | 🔑 {d.get('keywords','?')}\n"
                         f"📊 {d.get('achievements','?')} | 📝 {d.get('format','?')} | 🎯 <b>{d.get('overall','?')}/100</b> {get_level(d.get('overall',0))}\n") if d else f"🤖 ATS: {ats_r}\n"
            
            send_message(chat_id, f"📊 <b>ОЦЕНКА</b>\n{ats_block}📈 Общая: {ov_r}")
            send_message(chat_id, f"💪 <b>СИЛЬНЫЕ</b>:\n{str_r}\n⚠️ <b>СЛАБЫЕ</b>:\n{weak_r}")
            send_message(chat_id, f"💡 <b>СОВЕТЫ</b>:\n{rec_r}\n✅ Готово! Уровень: {get_level(ats_val)}")
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
