#!/usr/bin/env python3
import os, io, logging, requests, sqlite3, re, json
from datetime import datetime
from flask import Flask, request
from PyPDF2 import PdfReader
from concurrent.futures import ThreadPoolExecutor

# 🔐 Настройки
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY")
ADMIN_IDS = set(map(int, os.environ.get("ADMIN_IDS", "0").split(",")))
# WEBHOOK_SECRET — отключаем для тестов, включишь позже

if not TELEGRAM_TOKEN or not DEEPSEEK_API_KEY:
    raise ValueError("Missing TELEGRAM_TOKEN or DEEPSEEK_API_KEY")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

app = Flask(__name__)
DB_NAME = "resumeeasy.db"
resume_cache = {}

# ===== ГЛОБАЛЬНЫЙ СЛОВАРЬ КНОПОК (чтобы не было KeyError) =====
PART_MAP = {
    '🤖 ATS-рубрика': 'ats_score',
    '💪 Сильные стороны': 'strengths',
    '⚠️ Слабые стороны': 'weaknesses',
    '🔑 Ключевые слова': 'keywords',
    '💡 Советы (Было→Стало)': 'recommendations',
    '🎯 Вердикт': 'final_verdict',
    '✨ Переписать резюме': 'rewrite'
}

# ===== БАЗА ДАННЫХ =====
def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY, username TEXT, first_name TEXT,
        join_date TEXT, last_activity TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS analyses (
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER,
        resume_text TEXT, ats_score INTEGER, overall_score INTEGER,
        metrics_json TEXT, analysis_date TEXT)''')
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

def update_activity(user_id):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('UPDATE users SET last_activity=? WHERE user_id=?', (datetime.now().isoformat(), user_id))
    conn.commit()
    conn.close()

def get_user_stats(user_id):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('SELECT COUNT(*) FROM analyses WHERE user_id=?', (user_id,))
    total = c.fetchone()[0]
    c.execute('SELECT AVG(ats_score), AVG(overall_score) FROM analyses WHERE user_id=?', (user_id,))
    avg = c.fetchone()
    conn.close()
    return total, avg[0] or 0, avg[1] or 0

def get_all_stats():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('SELECT COUNT(*) FROM users')
    users = c.fetchone()[0]
    c.execute('SELECT COUNT(*) FROM analyses')
    analyses = c.fetchone()[0]
    c.execute('SELECT AVG(ats_score) FROM analyses WHERE ats_score>0')
    avg_ats = c.fetchone()[0] or 0
    c.execute('SELECT AVG(overall_score) FROM analyses WHERE overall_score>0')
    avg_ov = c.fetchone()[0] or 0
    conn.close()
    return users, analyses, avg_ats, avg_ov

# ===== УТИЛИТЫ =====
def send_message(chat_id, text, reply_markup=None, parse_mode="HTML"):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": parse_mode}
    if reply_markup:
        payload["reply_markup"] = json.dumps(reply_markup)
    try:
        requests.post(url, json=payload, timeout=30)
    except Exception as e:
        logger.error(f"Send error: {e}")

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
        text = "\n".join(page.extract_text() or "" for page in pdf.pages)
        return text.strip() if text.strip() else None
    except Exception as e:
        logger.error(f"PDF error: {e}")
        return None

def get_score_emoji(score):
    try:
        s = float(score)
        if s >= 90: return "🟢"
        if s >= 70: return "🟡"
        if s >= 50: return ""
        return "🔴"
    except:
        return "⚪"

# ===== AI =====
def analyze_part(resume_text, part_name):
    url = "https://api.deepseek.com/v1/chat/completions"
    headers = {"Authorization": f"Bearer {DEEPSEEK_API_KEY}", "Content-Type": "application/json"}
    
    prompts = {
        "ats_score": f"""Оцени резюме по 5 критериям (0-100 каждый):
1. Контакты 2. Структура 3. Ключевые слова 4. Достижения с цифрами 5. Формат
ВЕРНИ ТОЛЬКО JSON: {{"contacts": N, "structure": N, "keywords": N, "achievements": N, "format": N, "overall": N}}
Резюме:\n{resume_text[:4000]}""",
        "overall_score": f"Оцени резюме 0-100. ТОЛЬКО число.\nРезюме:\n{resume_text[:4000]}",
        "strengths": f"5-7 сильных сторон. ✅ в начале. БЕЗ *, #, HTML.\nРезюме:\n{resume_text[:4000]}",
        "weaknesses": f"5-7 слабых мест.  в начале. БЕЗ *, #, HTML.\nРезюме:\n{resume_text[:4000]}",
        "recommendations": f"5 советов в формате:\n❌ Проблема:\n✅ Решение:\n💡 Пример:\nБЕЗ *, #, HTML.\nРезюме:\n{resume_text[:4000]}",
        "keywords": f"8-12 ключевых слов через запятую. ТОЛЬКО слова.\nРезюме:\n{resume_text[:4000]}",
        "final_verdict": f"Вердикт: 1. Готово? (Да/Нет) 2. Топ-3 исправления 3. Конверсия %\nБез *, #, HTML.\nРезюме:\n{resume_text[:4000]}",
        "rewrite": f"Перепиши резюме идеально. Только текст. Цифры, глаголы действия. Без *, #, HTML.\nОригинал:\n{resume_text[:4000]}"
    }
    
    payload = {"model": "deepseek-chat", "messages": [{"role": "user", "content": prompts[part_name]}], "temperature": 0, "max_tokens": 2500}
    try:
        r = requests.post(url, headers=headers, json=payload, timeout=120)
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"].strip()
    except:
        return "⏳ Попробуй через минуту"

# ===== МЕНЮ =====
def show_main_menu(chat_id):
    kb = {"keyboard": [["📄 Загрузить резюме"], ["📊 Моя статистика", "❓ Помощь"], ["🔐 Админ-панель"]], "resize_keyboard": True}
    send_message(chat_id, "👋 <b>ResumeEasy Bot</b>\n📊 ATS-анализ резюме 2026\n🚀 Выбери действие", reply_markup=kb)

def show_analysis_menu(chat_id):
    kb = {"keyboard": [
        ["🚀 Полный разбор", "🤖 ATS-рубрика"],
        ["💪 Сильные стороны", "⚠️ Слабые стороны"],
        ["🔑 Ключевые слова", "💡 Советы (Было→Стало)"],
        ["🎯 Вердикт", "✨ Переписать резюме"],
        ["📄 Новое резюме", "⬅️ Назад в меню"]
    ], "resize_keyboard": True}
    send_message(chat_id, "✅ <b>Резюме загружено!</b>\n🎯 Выбери анализ:", reply_markup=kb)

# ===== ВЕБХУК =====
@app.route('/webhook', methods=['POST'])
def webhook():
    global resume_cache
    chat_id = None
    try:
        data = request.get_json()
        if not data or 'message' not in data:
            return 'ok', 200

        chat_id = data['message']['chat']['id']
        user = data['message']['from']
        save_user(chat_id, user.get('username','anon'), user.get('first_name',''))
        update_activity(chat_id)
        text = data['message'].get('text', '')
        
        logger.info(f"User {chat_id} sent: {repr(text)[:100]}")  # 🔍 Отладка: видим точный текст кнопки

        # 🏠 МЕНЮ
        if text in ['/start', '🏠 Главное меню', '⬅️ Назад в меню']:
            show_main_menu(chat_id)
            return 'ok', 200

        # ❓ ПОМОЩЬ
        if text == '❓ Помощь':
            send_message(chat_id, "📘 <b>Инструкция:</b>\n1. Загрузи PDF\n2. Выбери анализ\n⏱️ Жди 30 сек")
            return 'ok', 200

        # 📊 СТАТИСТИКА
        if text == '📊 Моя статистика':
            total, a, o = get_user_stats(chat_id)
            send_message(chat_id, f"📊 <b>Статистика</b>\n📄 Анализов: {total}\n{get_score_emoji(a)} ATS: {a:.1f}\n{get_score_emoji(o)} Общая: {o:.1f}")
            return 'ok', 200

        # 🔐 АДМИНКА
        if text == '🔐 Админ-панель':
            if chat_id not in ADMIN_IDS:
                send_message(chat_id, "🔐 Доступ запрещён")
                return 'ok', 200
            u, a, ats, ov = get_all_stats()
            send_message(chat_id, f"📊 <b>Админка</b>\n👥 {u} юзеров\n📄 {a} анализов\n📈 ATS: {ats:.1f} | Общая: {ov:.1f}")
            return 'ok', 200

        # 📄 ЗАГРУЗКА
        if text in ['📄 Загрузить резюме', '📄 Новое резюме']:
            send_message(chat_id, "📎 Отправь PDF (до 10 МБ, не скан)")
            return 'ok', 200

        # 📥 PDF
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
            furl = f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{finfo['result']['file_path']}"
            rtext = extract_text_from_pdf(requests.get(furl, timeout=60).content)
            if not rtext or len(rtext.split()) < 50:
                send_message(chat_id, "❌ Не удалось извлечь текст (возможно, скан)")
                return 'ok', 200
            resume_cache[chat_id] = rtext
            show_analysis_menu(chat_id)
            return 'ok', 200

        # 🧠 АНАЛИЗ ПО КНОПКЕ
        if text in PART_MAP:  # ✅ Используем глобальный словарь
            rtext = resume_cache.get(chat_id)
            if not rtext:
                show_main_menu(chat_id)
                send_message(chat_id, "❌ Сессия сброшена. Загрузи резюме заново.")
                return 'ok', 200
            send_message(chat_id, "⏳ Анализирую...")
            result = analyze_part(rtext, PART_MAP[text])
            
            if text == '🤖 ATS-рубрика':
                d = extract_json(result)
                if d and isinstance(d, dict):
                    out = f"🤖 <b>ATS</b>\n📞 {d.get('contacts','?')} | 📐 {d.get('structure','?')} | 🔑 {d.get('keywords','?')}\n📊 {d.get('achievements','?')} | 📝 {d.get('format','?')} | 🎯 <b>{d.get('overall','?')}/100</b>"
                else:
                    out = f"🤖 ATS: {result}"
            else:
                out = result
            send_message(chat_id, out)
            return 'ok', 200

        # 🚀 ПОЛНЫЙ РАЗБОР
        if text == '🚀 Полный разбор':
            rtext = resume_cache.get(chat_id)
            if not rtext:
                show_main_menu(chat_id)
                send_message(chat_id, "❌ Сессия сброшена")
                return 'ok', 200
            send_message(chat_id, "🚀 Глубокий анализ... ⏳")
            with ThreadPoolExecutor(max_workers=5) as ex:
                f1 = ex.submit(analyze_part, rtext, "ats_score")
                f2 = ex.submit(analyze_part, rtext, "overall_score")
                f3 = ex.submit(analyze_part, rtext, "strengths")
                f4 = ex.submit(analyze_part, rtext, "weaknesses")
                f5 = ex.submit(analyze_part, rtext, "recommendations")
                r1, r2, r3, r4, r5 = f1.result(), f2.result(), f3.result(), f4.result(), f5.result()
            d = extract_json(r1)
            ats = f"🤖 <b>ATS</b>\n📞 {d.get('contacts','?')} | 📐 {d.get('structure','?')} | 🔑 {d.get('keywords','?')}\n📊 {d.get('achievements','?')} | 📝 {d.get('format','?')} | 🎯 <b>{d.get('overall','?')}/100</b>\n\n" if d and isinstance(d,dict) else f"🤖 ATS: {r1}\n\n"
            send_message(chat_id, f"📊 <b>ПОЛНЫЙ ОТЧЁТ</b>\n\n{ats}📈 Общая: {r2}\n\n💪 <b>СИЛЬНЫЕ:</b>\n{r3}\n\n⚠️ <b>СЛАБЫЕ:</b>\n{r4}\n\n💡 <b>СОВЕТЫ:</b>\n{r5}")
            return 'ok', 200

        return 'ok', 200

    except Exception as e:
        logger.error(f"Webhook crash: {e}", exc_info=True)
        if chat_id:
            send_message(chat_id, f"❌ Ошибка: {str(e)[:150]}")
        return 'error', 500

@app.route('/', methods=['GET','HEAD'])
def index(): return '✅ ResumeEasy Bot Online', 200

@app.route('/health')
def health(): return {"status":"ok"}, 200

if __name__ != "__main__":
    init_db()
    logger.info("🚀 ResumeEasy Bot started")
