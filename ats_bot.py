#!/usr/bin/env python3
import os, io, logging, requests, re, json, time, uuid, csv
from datetime import datetime, timedelta
from flask import Flask, request, render_template_string, Response
from PyPDF2 import PdfReader
import psycopg2
import psycopg2.extras

# --- CONFIGURATION ---
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY")
ADMIN_IDS = set(map(int, os.environ.get("ADMIN_IDS", "0").split(",")))
DATABASE_URL = os.environ.get("DATABASE_URL")

if not TELEGRAM_TOKEN or not DEEPSEEK_API_KEY:
    raise ValueError("Missing TELEGRAM_TOKEN or DEEPSEEK_API_KEY")
if not DATABASE_URL:
    raise ValueError("Missing DATABASE_URL. Add PostgreSQL in Railway.")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Caches
report_cache = {} 
resume_cache = {}

# --- DATABASE ---
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
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendVideo"
    video_path = "welcome.mp4"
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
        send_message(chat_id, caption)

def clean_markdown(text):
    text = re.sub(r'\*\*(.*?)\*\*', r'\1', text)
    text = re.sub(r'\*(.*?)\*', r'\1', text)
    text = re.sub(r'___(.*?)___', r'\1', text)
    text = re.sub(r'__(.*?)__', r'\1', text)
    text = re.sub(r'_(.*?)_', r'\1', text)
    return text

def extract_json(text):
    text = re.sub(r'```json\s*|\s*```', '', text).strip()
    try: 
        return json.loads(text)
    except:
        m = re.search(r'\{.*\}', text, re.DOTALL)
        if m:
            try: 
                return json.loads(m.group())
            except: 
                pass
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
    except: 
        return "🌱 Новичок"

# --- AI ANALYSIS ---
def analyze_part(resume_text, part_name, timeout=60, custom_prompt=None, job_desc=None):
    url = "https://api.deepseek.com/v1/chat/completions"
    headers = {"Authorization": f"Bearer {DEEPSEEK_API_KEY}", "Content-Type": "application/json"}
    job_text = job_desc if job_desc else "Не указана"
    
    prompts = {
        "full_report": f"""Ты — старший HR-рекрутер и эксперт по ATS с 10+ лет опыта в России.
Проанализируй резюме и верни СТРОГО JSON со следующей структурой:

{{
  "overall_score": 0-100,
  "ats_score": 0-100,
  "keywords": ["найденные", "ключевые", "слова"],
  "headlines": ["Заголовок 1", "Заголовок 2", "Заголовок 3"],
  "critical_fixes": [
    {{"title": "Краткий заголовок проблемы", "description": "Конкретное описание, что заменить и как. Например: замените 'Моя история' на 'Опыт работы'.", "done": false}}
  ],
  "metrics_fixes": [
    {{"title": "Краткий заголовок", "description": "Конкретное описание с примером цифр. Например: вместо 'повысил продажи' напишите 'увеличил продажи на 35%'.", "done": false}}
  ],
  "style_fixes": [
    {{"title": "Краткий заголовок", "description": "Конкретное описание стилистической правки.", "done": false}}
  ],
  "hh_recommendations": "Советы по заполнению hh.ru",
  "match_vacancies": ["Вакансия 1", "Вакансия 2"],
  "verdict": "Общий вердикт"
}}

Важно:
- critical_fixes: минимум 2 проблемы ATS (заголовки, формат, отсутствие разделов)
- metrics_fixes: минимум 2 места где добавить цифры
- style_fixes: минимум 2 стилистических правки
- description ВСЕГДА конкретный — покажи на примере из резюме, что именно заменить

Резюме:
{resume_text[:4000]}""",
        
        "job_match": f"""Сравни резюме с вакансией. Верни СТРОГО JSON:
{{
  "match_percent": 0-100,
  "missing_skills": ["skill1", "skill2"],
  "recommendations": ["rec1", "rec2"],
  "summary": "Краткий итог на 2 предложения"
}}

Резюме:
{resume_text[:2000]}

Вакансия:
{job_text[:2000]}""",

        "cover_letter": f"""Ты — старший HR-рекрутер. Напиши короткое, ударное сопроводительное письмо для hh.ru.
Требования:
- 5-10 предложений.
- Первое предложение: имя, должность, ключевой результат.
- 3-4 буллита с достижениями под вакансию.
- Живой язык, без штампов.
- В конце: контакты.
- НЕ пиши "Резюме прилагаю".
- НЕ используй Markdown-разметку, только чистый текст.

Резюме:
{resume_text[:3000]}

Вакансия:
{job_text[:3000]}"""
    }
    
    payload = {
        "model": "deepseek-chat", 
        "messages": [{"role": "user", "content": custom_prompt or prompts.get(part_name, "")}], 
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

# --- REPORT TEMPLATES ---
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
        .checklist-item { display: flex; align-items: flex-start; padding: 12px; margin-bottom: 10px; background: #252525; border-radius: 8px; border-left: 4px solid #555; }
        .checklist-item.critical { border-left-color: #cf6679; }
        .checklist-item.metrics { border-left-color: #ffb74d; }
        .checklist-item.style { border-left-color: #03dac6; }
        .checklist-checkbox { margin-right: 12px; margin-top: 3px; width: 20px; height: 20px; cursor: pointer; }
        .checklist-content { flex: 1; }
        .checklist-title { font-weight: bold; margin-bottom: 4px; }
        .checklist-desc { font-size: 13px; color: #aaa; }
        .verdict-box { background: #1a1a2e; border: 1px solid #bb86fc; padding: 15px; border-radius: 8px; margin-top: 20px; }
        .verbatim { white-space: pre-wrap; background: #252525; padding: 15px; border-radius: 6px; font-size: 14px; }
        .footer { margin-top: 40px; text-align: center; font-size: 12px; color: #666; }
        .category-header { display: flex; align-items: center; gap: 10px; margin-top: 20px; }
        .category-badge { padding: 4px 10px; border-radius: 12px; font-size: 12px; font-weight: bold; }
        .badge-critical { background: #cf6679; color: #000; }
        .badge-metrics { background: #ffb74d; color: #000; }
        .badge-style { background: #03dac6; color: #000; }
        .btn-generate { display: block; width: 100%; padding: 15px; background: #bb86fc; color: #000; text-align: center; text-decoration: none; font-weight: bold; border-radius: 8px; margin-top: 20px; cursor: pointer; border: none; font-size: 16px; }
        .btn-generate:disabled { opacity: 0.5; cursor: not-allowed; }
        .btn-copy { display: block; width: 100%; padding: 15px; background: #03dac6; color: #000; text-align: center; text-decoration: none; font-weight: bold; border-radius: 8px; margin-top: 10px; cursor: pointer; border: none; font-size: 16px; }
        #improvedResume { margin-top: 30px; padding: 20px; background: #1a1a2e; border-radius: 10px; border: 2px solid #bb86fc; }
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

        <h2>✅ Чек-лист улучшений</h2>
        <p style="color:#888; font-size:13px">Отметьте правки, которые хотите применить → нажмите «Сгенерировать»</p>

        <div class="category-header">
            <span class="category-badge badge-critical">🔴 ATS-КРИТИЧНО</span>
            <span style="color:#aaa; font-size:13px">Мешают системам найти резюме</span>
        </div>
        {% for fix in critical_fixes %}
        <div class="checklist-item critical">
            <input type="checkbox" class="checklist-checkbox">
            <div class="checklist-content">
                <div class="checklist-title">{{ fix.title }}</div>
                <div class="checklist-desc">{{ fix.description }}</div>
            </div>
        </div>
        {% endfor %}

        <div class="category-header">
            <span class="category-badge badge-metrics">🟡 МЕТРИКИ</span>
            <span style="color:#aaa; font-size:13px">Добавьте цифры и результаты</span>
        </div>
        {% for fix in metrics_fixes %}
        <div class="checklist-item metrics">
            <input type="checkbox" class="checklist-checkbox">
            <div class="checklist-content">
                <div class="checklist-title">{{ fix.title }}</div>
                <div class="checklist-desc">{{ fix.description }}</div>
            </div>
        </div>
        {% endfor %}

        <div class="category-header">
            <span class="category-badge badge-style">🟢 СТИЛЬ</span>
            <span style="color:#aaa; font-size:13px">Язык, глаголы, подача</span>
        </div>
        {% for fix in style_fixes %}
        <div class="checklist-item style">
            <input type="checkbox" class="checklist-checkbox">
            <div class="checklist-content">
                <div class="checklist-title">{{ fix.title }}</div>
                <div class="checklist-desc">{{ fix.description }}</div>
            </div>
        </div>
        {% endfor %}

        <button class="btn-generate" onclick="generateResume()" id="genBtn">
            ✨ Сгенерировать улучшенное резюме
        </button>

        <div id="improvedResume" style="display:none;">
            <h2 style="color:#03dac6; margin-top:0;">✨ Улучшенное резюме</h2>
            <div class="verbatim" id="improvedText"></div>
            <button class="btn-copy" onclick="copyImproved()">📋 Скопировать текст</button>
        </div>

        <h2>🎯 Варианты заголовка для hh.ru</h2>
        <div class="verbatim">
        {% for h in headlines %}• {{ h }}<br>{% endfor %}
        </div>

        <h2>🔑 Ключевые слова для ATS</h2>
        <div>
        {% for k in keywords %}<span class="tag">{{ k }}</span>{% endfor %}
        </div>

        <h2>💡 Рекомендации по hh.ru</h2>
        <div class="verbatim">{{ hh_rec }}</div>

        <h2>📈 Подходящие вакансии</h2>
        <div class="verbatim">
        {% for v in match_vac %}• {{ v }}<br>{% endfor %}
        </div>

        <div class="verdict-box">
            <h2>🎤 Финальный вердикт</h2>
            <div class="verbatim">{{ verdict }}</div>
        </div>

        <div class="footer">Powered by ResumeEasy Bot</div>
    </div>

    <input type="hidden" id="reportId" value="{{ report_id }}">

    <script>
        function generateResume() {
            const selected = [];
            document.querySelectorAll('.checklist-checkbox:checked').forEach(cb => {
                const item = cb.closest('.checklist-item');
                selected.push({
                    title: item.querySelector('.checklist-title').innerText,
                    desc: item.querySelector('.checklist-desc').innerText
                });
            });
            
            if (selected.length === 0) {
                alert('Выберите хотя бы одну правку!');
                return;
            }
            
            document.getElementById('genBtn').innerText = '⏳ Генерирую...';
            document.getElementById('genBtn').disabled = true;
            
            fetch('/api/improve', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({report_id: document.getElementById('reportId').value, fixes: selected})
            })
            .then(r => r.json())
            .then(data => {
                document.getElementById('improvedText').innerText = data.text;
                document.getElementById('improvedResume').style.display = 'block';
                document.getElementById('genBtn').innerText = '✅ Готово!';
                document.getElementById('genBtn').disabled = false;
            })
            .catch(() => {
                document.getElementById('genBtn').innerText = '❌ Ошибка';
                document.getElementById('genBtn').disabled = false;
            });
        }

        function copyImproved() {
            navigator.clipboard.writeText(document.getElementById('improvedText').innerText)
                .then(() => alert('Скопировано!'));
        }
    </script>
</body>
</html>
"""

MATCH_HTML = """
<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Job Match Report</title>
    <style>
        body { background-color: #121212; color: #e0e0e0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; margin: 0; padding: 20px; line-height: 1.6; }
        .container { max-width: 800px; margin: 0 auto; background: #1e1e1e; padding: 30px; border-radius: 12px; box-shadow: 0 4px 20px rgba(0,0,0,0.5); }
        h1 { color: #ffffff; border-bottom: 2px solid #333; padding-bottom: 15px; margin-top: 0; font-size: 24px; }
        h2 { color: #bb86fc; margin-top: 30px; font-size: 18px; border-left: 4px solid #bb86fc; padding-left: 10px; }
        .score-card { background: #2c2c2c; padding: 20px; border-radius: 8px; text-align: center; margin-bottom: 20px; }
        .score-val { font-size: 48px; font-weight: bold; color: #03dac6; }
        .score-label { font-size: 16px; color: #aaa; margin-top: 5px; }
        .list-item { background: #252525; padding: 10px; margin-bottom: 8px; border-radius: 6px; border-left: 3px solid #cf6679; }
        .rec-item { background: #252525; padding: 10px; margin-bottom: 8px; border-radius: 6px; border-left: 3px solid #03dac6; }
        .summary { background: #333; padding: 15px; border-radius: 6px; margin-bottom: 20px; font-style: italic; }
        .footer { margin-top: 40px; text-align: center; font-size: 12px; color: #666; }
    </style>
</head>
<body>
    <div class="container">
        <h1>🎯 Job Match Analysis</h1>
        <p style="color: #888">Generated on {{ date }}</p>
        <div class="score-card">
            <div class="score-val">{{ match }}/100</div>
            <div class="score-label">Совпадение с вакансией</div>
        </div>
        <div class="summary">{{ summary }}</div>
        <h2>❌ Недостающие навыки</h2>
        {% for skill in missing %}<div class="list-item">• {{ skill }}</div>{% endfor %}
        <h2>💡 Рекомендации по улучшению</h2>
        {% for rec in recs %}<div class="rec-item">• {{ rec }}</div>{% endfor %}
        <div class="footer">Powered by ResumeEasy Bot</div>
    </div>
</body>
</html>
"""

COVER_HTML = """
<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Cover Letter</title>
    <style>
        body { background-color: #121212; color: #e0e0e0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; margin: 0; padding: 20px; line-height: 1.6; }
        .container { max-width: 800px; margin: 0 auto; background: #1e1e1e; padding: 40px; border-radius: 12px; box-shadow: 0 4px 20px rgba(0,0,0,0.5); }
        h1 { color: #ffffff; border-bottom: 2px solid #333; padding-bottom: 15px; margin-top: 0; font-size: 24px; }
        .letter-content { white-space: pre-wrap; background: #252525; padding: 20px; border-radius: 8px; font-size: 16px; line-height: 1.8; border: 1px solid #333; }
        .btn-copy { display: block; width: 100%; padding: 15px; background: #03dac6; color: #000; text-align: center; text-decoration: none; font-weight: bold; border-radius: 8px; margin-top: 20px; cursor: pointer; border: none; font-size: 16px; }
        .footer { margin-top: 40px; text-align: center; font-size: 12px; color: #666; }
    </style>
</head>
<body>
    <div class="container">
        <h1>📝 Сопроводительное письмо</h1>
        <p style="color: #888">Готово к отправке на hh.ru</p>
        <div class="letter-content" id="letterText">{{ letter }}</div>
        <button class="btn-copy" onclick="copyText()">📋 Скопировать текст</button>
        <div class="footer">Powered by ResumeEasy Bot</div>
    </div>
    <script>
        function copyText() {
            navigator.clipboard.writeText(document.getElementById("letterText").innerText)
                .then(() => alert("Текст скопирован!"));
        }
    </script>
</body>
</html>
"""

ADMIN_HTML = """
<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>ResumeEasy Admin</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { background: #0a0a0a; color: #e0e0e0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
        .sidebar { position: fixed; left: 0; top: 0; width: 220px; height: 100vh; background: #111; padding: 20px; border-right: 1px solid #222; }
        .sidebar h2 { color: #bb86fc; margin-bottom: 30px; font-size: 20px; }
        .sidebar a { display: block; color: #888; text-decoration: none; padding: 10px; border-radius: 6px; margin-bottom: 5px; transition: 0.2s; }
        .sidebar a:hover, .sidebar a.active { background: #1e1e1e; color: #fff; }
        .main { margin-left: 220px; padding: 30px; }
        .stats-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 15px; margin-bottom: 30px; }
        .stat-card { background: #1e1e1e; padding: 20px; border-radius: 10px; border: 1px solid #333; }
        .stat-card .value { font-size: 32px; font-weight: bold; color: #03dac6; }
        .stat-card .label { font-size: 13px; color: #888; margin-top: 5px; }
        .chart-container { background: #1e1e1e; padding: 20px; border-radius: 10px; border: 1px solid #333; margin-bottom: 20px; }
        table { width: 100%; border-collapse: collapse; background: #1e1e1e; border-radius: 10px; overflow: hidden; }
        th { background: #252525; padding: 12px; text-align: left; font-size: 13px; color: #888; text-transform: uppercase; }
        td { padding: 12px; border-top: 1px solid #333; font-size: 14px; }
        tr:hover td { background: #252525; }
        .badge { padding: 3px 8px; border-radius: 10px; font-size: 11px; font-weight: bold; }
        .badge-new { background: #03dac6; color: #000; }
        .badge-active { background: #bb86fc; color: #000; }
        .badge-inactive { background: #333; color: #888; }
        .btn { padding: 8px 16px; border-radius: 6px; border: none; cursor: pointer; font-weight: bold; text-decoration: none; display: inline-block; }
        .btn-primary { background: #bb86fc; color: #000; }
        .btn-export { background: #03dac6; color: #000; }
    </style>
</head>
<body>
    <div class="sidebar">
        <h2>📊 ResumeEasy</h2>
        <a href="/admin" class="active">🏠 Дашборд</a>
        <a href="/admin/users">👥 Пользователи</a>
        <a href="/admin/export">📥 Экспорт CSV</a>
    </div>
    <div class="main">
        <h1 style="margin-bottom: 5px;">Дашборд</h1>
        <p style="color: #888; margin-bottom: 25px;">Обновлено: {{ now }}</p>
        <div class="stats-grid">
            <div class="stat-card"><div class="value">{{ total_users }}</div><div class="label">👥 Всего пользователей</div></div>
            <div class="stat-card"><div class="value">{{ new_today }}</div><div class="label">🆕 Новых сегодня</div></div>
            <div class="stat-card"><div class="value">{{ total_analyses }}</div><div class="label">📊 Всего анализов</div></div>
            <div class="stat-card"><div class="value">{{ active_week }}</div><div class="label">🔥 Активных за 7 дней</div></div>
        </div>
        <div class="chart-container"><canvas id="userChart" height="120"></canvas></div>
        <h2 style="margin-bottom: 15px;">Последние пользователи</h2>
        <table>
            <thead><tr><th>ID</th><th>Имя</th><th>Username</th><th>Анализов</th><th>Ср. ATS</th><th>Активность</th><th>Статус</th></tr></thead>
            <tbody>
                {% for u in users %}
                <tr>
                    <td>{{ u.user_id }}</td>
                    <td>{{ u.first_name or '—' }}</td>
                    <td>{{ u.username or '—' }}</td>
                    <td>{{ u.total }}</td>
                    <td>{{ "%.0f"|format(u.avg_ats) }}</td>
                    <td>{{ u.last_activity.strftime('%d.%m.%Y') if u.last_activity else '—' }}</td>
                    <td>{% if u.total == 0 %}<span class="badge badge-new">NEW</span>{% else %}<span class="badge badge-active">ACTIVE</span>{% endif %}</td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
    </div>
    <script>
        new Chart(document.getElementById('userChart'), {
            type: 'line',
            data: { labels: {{ chart_labels | tojson }}, datasets: [{ label: 'Новые', data: {{ chart_data | tojson }}, borderColor: '#bb86fc', backgroundColor: 'rgba(187,134,252,0.1)', fill: true, tension: 0.4 }] },
            options: { responsive: true, plugins: { legend: { display: false } }, scales: { y: { beginAtZero: true, grid: { color: '#333' } }, x: { grid: { color: '#333' } } } }
        });
    </script>
</body>
</html>
"""

ADMIN_USERS_HTML = """
<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8"><title>Users - ResumeEasy Admin</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { background: #0a0a0a; color: #e0e0e0; font-family: -apple-system, sans-serif; }
        .sidebar { position: fixed; left: 0; top: 0; width: 220px; height: 100vh; background: #111; padding: 20px; border-right: 1px solid #222; }
        .sidebar h2 { color: #bb86fc; margin-bottom: 30px; }
        .sidebar a { display: block; color: #888; text-decoration: none; padding: 10px; border-radius: 6px; margin-bottom: 5px; }
        .sidebar a:hover, .sidebar a.active { background: #1e1e1e; color: #fff; }
        .main { margin-left: 220px; padding: 30px; }
        table { width: 100%; border-collapse: collapse; background: #1e1e1e; border-radius: 10px; overflow: hidden; }
        th { background: #252525; padding: 12px; text-align: left; font-size: 13px; color: #888; }
        td { padding: 12px; border-top: 1px solid #333; font-size: 14px; }
        tr:hover td { background: #252525; }
    </style>
</head>
<body>
    <div class="sidebar">
        <h2>📊 ResumeEasy</h2>
        <a href="/admin">🏠 Дашборд</a>
        <a href="/admin/users" class="active">👥 Пользователи</a>
        <a href="/admin/export">📥 Экспорт CSV</a>
    </div>
    <div class="main">
        <h1>Все пользователи</h1>
        <table>
            <thead><tr><th>ID</th><th>Имя</th><th>Username</th><th>Дата регистрации</th><th>Активность</th><th>Анализов</th><th>Ср. ATS</th></tr></thead>
            <tbody>
                {% for u in users %}
                <tr>
                    <td>{{ u.user_id }}</td>
                    <td>{{ u.first_name or '—' }}</td>
                    <td>{{ u.username or '—' }}</td>
                    <td>{{ u.join_date.strftime('%d.%m.%Y') if u.join_date else '—' }}</td>
                    <td>{{ u.last_activity.strftime('%d.%m.%Y') if u.last_activity else '—' }}</td>
                    <td>{{ u.total }}</td>
                    <td>{{ "%.0f"|format(u.avg_ats) }}</td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
    </div>
</body>
</html>
"""

# --- ROUTES ---
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

@app.route('/api/improve', methods=['POST'])
def api_improve():
    data = request.get_json()
    report_id = data.get('report_id')
    fixes = data.get('fixes', [])
    report = report_cache.get(report_id)
    if not report:
        return {"error": "Report expired"}, 404
    user_id = report.get('user_id')
    resume_text = resume_cache.get(user_id) or get_last_analysis_text(user_id)
    fixes_text = "\n".join([f"- {f['title']}: {f['desc']}" for f in fixes])
    prompt = f"""Улучши резюме, применив ТОЛЬКО указанные правки. Остальной текст не меняй. Верни ПОЛНЫЙ текст улучшенного резюме.

Исходное резюме:
{resume_text}

Применить эти правки:
{fixes_text}

Улучшенное резюме (полный текст):"""
    result = analyze_part("", "", custom_prompt=prompt, timeout=90)
    return {"text": result or "Ошибка генерации"}

@app.route('/admin')
@app.route('/admin/')
def admin_dashboard():
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

@app.route('/admin/users')
def admin_users():
    conn = get_db()
    c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    c.execute('''SELECT u.user_id, u.username, u.first_name, u.join_date, u.last_activity,
        COUNT(a.id) as total, COALESCE(AVG(a.ats_score), 0) as avg_ats
        FROM users u LEFT JOIN analyses a ON u.user_id = a.user_id
        GROUP BY u.user_id ORDER BY u.last_activity DESC NULLS LAST''')
    users = c.fetchall()
    conn.close()
    return render_template_string(ADMIN_USERS_HTML, users=users, now=datetime.now())

@app.route('/admin/export')
def admin_export():
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
            send_message(chat_id, "📘 <b>Как пользоваться:</b>\n1. Загрузи PDF\n2. Нажми «Получить отчет»\n3. Отметь нужные правки\n4. Нажми «Сгенерировать» — получишь готовое улучшенное резюме!"); return 'ok', 200
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
            finfo = requests.get(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getFile?file_id={fid}", timeout=30).json()
            if not finfo.get('ok'): send_message(chat_id, "❌ Ошибка файла"); return 'ok', 200
            rtext = extract_text_from_pdf(requests.get(f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{finfo['result']['file_path']}", timeout=60).content)
            if not rtext or len(rtext.split()) < 50: send_message(chat_id, "❌ Текст не извлечён"); return 'ok', 200
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
                send_message(chat_id, "📝 <b>Сопроводительное письмо</b>\n\nУ вас есть сохранённая вакансия.", reply_markup=kb)
            else:
                kb = {"keyboard": [["🆕 Указать вакансию"], ["📝 Без вакансии (общее)"]], "resize_keyboard": True}
                send_message(chat_id, "📝 <b>Сопроводительное письмо</b>\n\nПод вакансию или общее?", reply_markup=kb)
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
            res = analyze_part(rtext, "full_report", timeout=90)
            d = extract_json(res)
            if not d: send_message(chat_id, "❌ Не удалось сформировать отчет."); return 'ok', 200
            save_analysis(chat_id, rtext, d.get('ats_score', 0), d.get('overall_score', 0), "full_report")
            report_id = str(uuid.uuid4())
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

# --- STARTUP ---
init_db()
logger.info("🚀 Started")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
