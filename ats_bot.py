#!/usr/bin/env python3
import os, io, logging, requests, sqlite3, re, json, time
from datetime import datetime
from flask import Flask, request
from PyPDF2 import PdfReader

# 🔐 Настройки
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY")
ADMIN_IDS = set(map(int, os.environ.get("ADMIN_IDS", "0").split(",")))

if not TELEGRAM_TOKEN or not DEEPSEEK_API_KEY:
    raise ValueError("Missing TELEGRAM_TOKEN or DEEPSEEK_API_KEY")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

app = Flask(__name__)
DB_NAME = "resumeeasy.db"
resume_cache = {}

# ===== ГЛОБАЛЬНЫЙ СЛОВАРЬ КНОПОК =====
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
        if s >= 90: return "🟢 Отлично"
        if s >= 70: return "🟡 Хорошо"
        if s >= 50: return "🟠 Нормально"
        return "🔴 Нужно доработать"
    except:
        return "⚪ Ошибка"

# ===== AI =====
def analyze_part(resume_text, part_name, timeout=60):
    url = "https://api.deepseek.com/v1/chat/completions"
    headers = {"Authorization": f"Bearer {DEEPSEEK_API_KEY}", "Content-Type": "application/json"}
    
    prompts = {
        "ats_score": f"""Оцени резюме по 5 критериям (каждый 0-100):
1. Контакты (есть ли email, телефон, ссылки)
2. Структура (логика разделов, порядок)
3. Ключевые слова (совпадение с вакансиями 2026)
4. Достижения с цифрами (%, ₽, сроки, масштабы)
5. Формат (нет воды, глаголы действия, стиль)

ВЕРНИ ТОЛЬКО JSON:
{{"contacts": N, "structure": N, "keywords": N, "achievements": N, "format": N, "overall": N}}

Резюме:\n{resume_text[:4000]}""",
        
        "overall_score": f"Оцени общее качество резюме числом от 0 до 100. ТОЛЬКО число, без текста.\nРезюме:\n{resume_text[:4000]}",
        
        "strengths": f"""Выдели 5-7 сильных сторон резюме.
ПРАВИЛА:
- Начинай каждый пункт с ✅
- Пиши обычный текст, без *, #, HTML
- Конкретика, без воды

Резюме:\n{resume_text[:4000]}""",
        
        "weaknesses": f"""Выдели 5-7 слабых мест и ошибок.
ПРАВИЛА:
- Начинай каждый пункт с 
- Пиши обычный текст, без *, #, HTML
- Конкретика, что исправить

Резюме:\n{resume_text[:4000]}""",
        
        "recommendations": f"""Дай 5 конкретных рекомендаций в формате:

❌ Проблема: [что не так]
✅ Решение: [как исправить]
💡 Пример: [готовая фраза для вставки в резюме]

ПРАВИЛА:
- БЕЗ *, #, HTML
- Примеры должны быть под стиль резюме
- Глаголы действия: увеличил, запустил, оптимизировал

Резюме:\n{resume_text[:4000]}""",
        
        "keywords": f"Выдай 8-12 ключевых слов для ATS через запятую. ТОЛЬКО слова, без лишнего текста.\nРезюме:\n{resume_text[:4000]}",
        
        "final_verdict": f"""Дай чёткий финальный вердикт по резюме.

ФОРМАТ ОТВЕТА (строго):

🎯 ГОТОВНОСТЬ: [Да/Нет/Частично]

❌ КРИТИЧЕСКИЕ ОШИБКИ (макс. 3):
• [ошибка 1]
• [ошибка 2]
• [ошибка 3]

📈 ПРОГНОЗ: [число]% шанс получить приглашение на собеседование

💡 ГЛАВНЫЙ СОВЕТ: [одна фраза, что сделать в первую очередь]

Без *, #, HTML. Только обычный текст с эмодзи.

Резюме:\n{resume_text[:4000]}""",
        
        "rewrite": f"""Перепиши резюме в идеальном варианте.

ПРАВИЛА:
- Только обычный текст (plain text)
- Добавь цифры и конкретику
- Убери воду и общие фразы
- Используй глаголы действия: разработал, увеличил, внедрил
- БЕЗ *, #, HTML, жирного шрифта

Оригинал:\n{resume_text[:4000]}"""
    }
    
    payload = {
        "model": "deepseek-chat",
        "messages": [{"role": "user", "content": prompts[part_name]}],
        "temperature": 0,
        "max_tokens": 2500
    }
    
    try:
        r = requests.post(url, headers=headers, json=payload, timeout=timeout)
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"].strip()
    except requests.exceptions.Timeout:
        return "⏳ Сервис перегружен, попробуй через минуту"
    except Exception as e:
        logger.error(f"AI error [{part_name}]: {e}")
        return "🔧 Временная ошибка анализа"

# ===== МЕНЮ =====
def show_main_menu(chat_id):
    kb = {"keyboard": [["📄 Загрузить резюме"], ["📊 Моя статистика", "❓ Помощь"], ["🔐 Админ-панель"]], "resize_keyboard": True}
    send_message(chat_id, 
        "👋 <b>ResumeEasy Bot</b> — твой ATS-эксперт ✨\n\n"
        "📊 Анализирую резюме по стандартам 2026:\n"
        "• Совместимость с парсерами (ATS)\n"
        "• Качество контента и структуры\n"
        "• Ключевые слова для поиска\n"
        "• Конкретные советы по улучшению\n\n"
        "🚀 Нажми «Загрузить резюме» чтобы начать", 
        reply_markup=kb)

def show_analysis_menu(chat_id):
    kb = {"keyboard": [
        ["🚀 Полный разбор", "🤖 ATS-рубрика"],
        ["💪 Сильные стороны", "⚠️ Слабые стороны"],
        ["🔑 Ключевые слова", "💡 Советы (Было→Стало)"],
        ["🎯 Вердикт", "✨ Переписать резюме"],
        ["📄 Новое резюме", "⬅️ Назад в меню"]
    ], "resize_keyboard": True}
    send_message(chat_id, 
        "✅ <b>Резюме загружено!</b>\n\n"
        "🎯 Выбери, что хочешь получить:\n"
        "• 🤖 ATS-рубрика — детальный разбор по 5 критериям\n"
        "• 🚀 Полный разбор — всё сразу (займёт ~2 мин)\n"
        "• 💡 Советы — готовые фразы для улучшения", 
        reply_markup=kb)

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
        
        logger.info(f"User {chat_id} sent: {repr(text)[:100]}")

        # 🏠 ГЛАВНОЕ МЕНЮ
        if text in ['/start', '🏠 Главное меню', '⬅️ Назад в меню']:
            show_main_menu(chat_id)
            return 'ok', 200

        # ❓ ПОМОЩЬ
        if text == '❓ Помощь':
            send_message(chat_id, 
                "📘 <b>Как пользоваться:</b>\n\n"
                "1️⃣ Нажми «📄 Загрузить резюме»\n"
                "2️⃣ Отправь файл в формате PDF (до 10 МБ)\n"
                "3️⃣ Дождись подтверждения и выбери анализ:\n"
                "   • 🤖 ATS-рубрика — детальный разбор по 5 метрикам\n"
                "   • 🚀 Полный разбор — всё сразу (~2 минуты)\n"
                "   • 💡 Советы — готовые фразы «было → стало»\n\n"
                "⏱️ Обычное время анализа: 20-40 секунд")
            return 'ok', 200

        # 📊 СТАТИСТИКА
        if text == '📊 Моя статистика':
            total, a, o = get_user_stats(chat_id)
            send_message(chat_id, 
                f"📊 <b>Твоя статистика</b>\n\n"
                f"📄 Проанализировано резюме: {total}\n"
                f"{get_score_emoji(a)} Средний ATS-балл: {a:.1f}/100\n"
                f"{get_score_emoji(o)} Средняя общая оценка: {o:.1f}/100")
            return 'ok', 200

        # 🔐 АДМИНКА
        if text == '🔐 Админ-панель':
            if chat_id not in ADMIN_IDS:
                send_message(chat_id, "🔐 Доступ запрещён. Обратитесь к разработчику.")
                return 'ok', 200
            u, a, ats, ov = get_all_stats()
            send_message(chat_id, 
                f"📊 <b>Панель управления</b>\n\n"
                f"👥 Всего пользователей: {u}\n"
                f"📄 Всего анализов: {a}\n"
                f"📈 Средний ATS-балл: {ats:.1f}/100\n"
                f"📈 Средняя общая оценка: {ov:.1f}/100\n\n"
                f"🕒 {datetime.now().strftime('%d.%m.%Y %H:%M')}")
            return 'ok', 200

        # 📄 ЗАГРУЗКА
        if text in ['📄 Загрузить резюме', '📄 Новое резюме']:
            send_message(chat_id, 
                "📎 <b>Отправь файл с резюме</b>\n\n"
                "✅ Поддерживаемый формат: PDF\n"
                "✅ Макс. размер: 10 МБ\n"
                "❌ Не отправляй сканы/картинки — только текстовый PDF\n\n"
                "🔄 Анализ начнётся автоматически после получения файла")
            return 'ok', 200

        # 📥 ОБРАБОТКА PDF
        if 'document' in data['message']:
            doc = data['message']['document']
            if doc.get('file_size', 0) > 10*1024*1024:
                send_message(chat_id, "❌ Файл слишком большой. Макс. размер: 10 МБ.")
                return 'ok', 200
            if doc.get('mime_type') != 'application/pdf':
                send_message(chat_id, "❌ Поддерживается только формат PDF.")
                return 'ok', 200
            
            send_message(chat_id, "🔍 Извлекаю текст из PDF... ⏳")
            fid = doc['file_id']
            finfo = requests.get(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getFile?file_id={fid}", timeout=30).json()
            if not finfo.get('ok'):
                send_message(chat_id, "❌ Не удалось получить файл. Попробуй ещё раз.")
                return 'ok', 200
            furl = f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{finfo['result']['file_path']}"
            rtext = extract_text_from_pdf(requests.get(furl, timeout=60).content)
            if not rtext or len(rtext.split()) < 50:
                send_message(chat_id, "❌ Не удалось извлечь текст. Возможно, это скан или изображение. Отправь текстовый PDF.")
                return 'ok', 200
            resume_cache[chat_id] = rtext
            show_analysis_menu(chat_id)
            return 'ok', 200

        # 🧠 ИНДИВИДУАЛЬНЫЙ АНАЛИЗ
        if text in PART_MAP:
            rtext = resume_cache.get(chat_id)
            if not rtext:
                show_main_menu(chat_id)
                send_message(chat_id, "❌ Сессия истекла. Загрузи резюме заново.")
                return 'ok', 200
            
            send_message(chat_id, "⏳ Анализирую... (20-40 сек)")
            result = analyze_part(rtext, PART_MAP[text], timeout=60)
            
            # Форматируем ATS-рубрику с ПОДПИСЯМИ
            if text == '🤖 ATS-рубрика':
                d = extract_json(result)
                if d and isinstance(d, dict):
                    out = (f"🤖 <b>ATS-РУБРИКА</b> — совместимость с системами отбора:\n\n"
                           f"📞 <b>Контакты</b>: {d.get('contacts','?')}/100\n"
                           f"   • Email, телефон, LinkedIn/портфолио\n"
                           f"📐 <b>Структура</b>: {d.get('structure','?')}/100\n"
                           f"   • Логика разделов, порядок, читаемость\n"
                           f"🔑 <b>Ключевые слова</b>: {d.get('keywords','?')}/100\n"
                           f"   • Совпадение с требованиями вакансий\n"
                           f"📊 <b>Достижения</b>: {d.get('achievements','?')}/100\n"
                           f"   • Цифры, результаты, масштабы проектов\n"
                           f"📝 <b>Формат</b>: {d.get('format','?')}/100\n"
                           f"   • Нет воды, глаголы действия, стиль\n\n"
                           f"🎯 <b>ИТОГОВЫЙ БАЛЛ: {d.get('overall','?')}/100</b> {get_score_emoji(d.get('overall',0))}")
                else:
                    out = f"🤖 ATS-анализ: {result}"
            else:
                out = result
            send_message(chat_id, out)
            return 'ok', 200

        # 🚀 ПОЛНЫЙ РАЗБОР (ПОСЛЕДОВАТЕЛЬНО, с прогрессом)
        if text == '🚀 Полный разбор':
            rtext = resume_cache.get(chat_id)
            if not rtext:
                show_main_menu(chat_id)
                send_message(chat_id, "❌ Сессия истекла. Загрузи резюме заново.")
                return 'ok', 200
            
            # Отправляем прогресс-сообщения
            send_message(chat_id, "🚀 <b>Запускаю глубокий анализ</b>\n⏳ Это займёт ~2 минуты")
            time.sleep(1)
            send_message(chat_id, "🔍 Проверяю ATS-совместимость...")
            
            # Делаем запросы ПОСЛЕДОВАТЕЛЬНО (чтобы не было таймаута Render)
            ats_r = analyze_part(rtext, "ats_score", timeout=45)
            send_message(chat_id, "📊 Оцениваю общее качество...")
            ov_r = analyze_part(rtext, "overall_score", timeout=30)
            send_message(chat_id, "💪 Анализирую сильные стороны...")
            str_r = analyze_part(rtext, "strengths", timeout=45)
            send_message(chat_id, "⚠️ Ищу слабые места...")
            weak_r = analyze_part(rtext, "weaknesses", timeout=45)
            send_message(chat_id, "💡 Готовлю советы...")
            rec_r = analyze_part(rtext, "recommendations", timeout=45)
            
            # Формируем отчёт
            d = extract_json(ats_r)
            if d and isinstance(d, dict):
                ats_block = (f"🤖 <b>ATS-РУБРИКА</b>\n"
                             f"📞 Контакты: {d.get('contacts','?')} | 📐 Структура: {d.get('structure','?')}\n"
                             f"🔑 Ключевые: {d.get('keywords','?')} | 📊 Достижения: {d.get('achievements','?')}\n"
                             f"📝 Формат: {d.get('format','?')} | 🎯 <b>ИТОГО: {d.get('overall','?')}/100</b>\n\n")
            else:
                ats_block = f"🤖 ATS: {ats_r}\n\n"
            
            full = (f"📊 <b>ПОЛНЫЙ ОТЧЁТ</b>\n\n"
                    f"{ats_block}"
                    f"📈 <b>Общая оценка</b>: {ov_r}\n\n"
                    f"💪 <b>СИЛЬНЫЕ СТОРОНЫ</b>:\n{str_r}\n\n"
                    f"⚠️ <b>СЛАБЫЕ МЕСТА</b>:\n{weak_r}\n\n"
                    f"💡 <b>СОВЕТЫ (Было → Стало)</b>:\n{rec_r}\n\n"
                    f"<i>💬 Хочешь вердикт или переписать резюме? Выбери в меню выше</i>")
            send_message(chat_id, full)
            return 'ok', 200

        # Неизвестная команда
        return 'ok', 200

    except Exception as e:
        logger.error(f"Webhook crash: {e}", exc_info=True)
        if chat_id:
            send_message(chat_id, f"❌ Произошла ошибка: {str(e)[:150]}")
        return 'error', 500

@app.route('/', methods=['GET','HEAD'])
def index(): 
    return '✅ ResumeEasy Bot Online', 200

@app.route('/health')
def health(): 
    return {"status":"ok", "service":"ResumeEasy Bot"}, 200

# Инициализация
if __name__ != "__main__":
    init_db()
    logger.info("🚀 ResumeEasy Bot started")
