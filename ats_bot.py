#!/usr/bin/env python3
import os, io, logging, requests, sqlite3, re, json, time, textwrap
from datetime import datetime
from flask import Flask, request
from PyPDF2 import PdfReader

# 🔐 Настройки
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY")
ADMIN_IDS = set(map(int, os.environ.get("ADMIN_IDS", "0").split(",")))

if not TELEGRAM_TOKEN or not DEEPSEEK_API_KEY:
    raise ValueError("Missing tokens")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

app = Flask(__name__)
DB_NAME = "resumeeasy.db"  # ✅ Локальная БД (работает на free tier)
resume_cache = {}

# ===== БАЗА ДАННЫХ =====
def init_db():
    # ✅ Убрали os.makedirs — создаём БД в текущей папке
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

# ===== УТИЛИТЫ =====
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

# ===== AI =====
def analyze_part(resume_text, part_name, timeout=45, custom_prompt=None):
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
    
    payload = {
        "model": "deepseek-chat",
        "messages": [{"role": "user", "content": custom_prompt or prompts[part_name]}],
        "temperature": 0, "max_tokens": 2500
    }
    try:
        r = requests.post(url, headers=headers, json=payload, timeout=timeout)
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"].strip()
    except: return "⏳ Попробуй через минуту"

# ===== МЕНЮ =====
def show_main_menu(chat_id):
    kb = {"keyboard": [
        ["📄 Загрузить резюме"],
        ["🎯 Сравнить с вакансией", "📈 Моя история"],
        ["❓ Помощь", "🔐 Админ-панель"]
    ], "resize_keyboard": True}
    send_message(chat_id, "👋 <b>ResumeEasy Bot</b>\n📊 ATS-анализ, история, уровни", reply_markup=kb)

def show_analysis_menu(chat_id):
    kb = {"keyboard": [
        ["🚀 Полный разбор", "🤖 ATS-рубрика"],
        ["💪 Сильные стороны", "⚠️ Слабые стороны"],
        ["🔑 Ключевые слова", "💡 Советы (Было→Стало)"],
        ["🎯 Вердикт", "✨ Переписать резюме"],
        ["📤 Скачать отчёт", "🔄 Улучшить пункт"],
        ["📄 Новое резюме", "⬅️ Назад в меню"]
    ], "resize_keyboard": True}
    send_message(chat_id, "✅ <b>Резюме загружено!</b>\n🎯 Выбери анализ:", reply_markup=kb)

# ===== ВЕБХУК =====
@app.route('/webhook', methods=['POST'])
def webhook():
    chat_id = None
    try:
        data = request.get_json()
        if not data or 'message' not in  return 'ok', 200

        chat_id = data['message']['chat']['id']
        user = data['message']['from']
        save_user(chat_id, user.get('username','anon'), user.get('first_name',''))
        text = data['message'].get('text', '')

        # 🏠 МЕНЮ
        if text in ['/start', '⬅️ Назад в меню']:
            show_main_menu(chat_id)
            return 'ok', 200

        # ❓ ПОМОЩЬ
        if text == '❓ Помощь':
            send_message(chat_id, "📘 <b>Как пользоваться:</b>\n1. Загрузи PDF\n2. Выбери анализ\n3. Смотри историю и уровни")
            return 'ok', 200

        # 📈 ИСТОРИЯ
        if text == '📈 Моя история':
            hist = get_user_history(chat_id, 5)
            if not hist:
                send_message(chat_id, "📭 Истории пока нет. Загрузи резюме!")
                return 'ok', 200
            msg = "📈 <b>Твои анализы:</b>\n\n"
            for i, (date, ats, ov, typ) in enumerate(hist, 1):
                msg += f"{i}. {date[:10]} | ATS: {ats or '?'} | Общая: {ov or '?'}\n"
            msg += f"\n🏆 Уровень: {get_level(hist[0][2] if hist[0][2] else 0)}"
            send_message(chat_id, msg)
            return 'ok', 200

        # 🔐 АДМИНКА
        if text == '🔐 Админ-панель':
            if chat_id not in ADMIN_IDS:
                send_message(chat_id, "🔐 Доступ запрещён")
                return 'ok', 200
            users = get_all_users(10)
            msg = "📊 <b>Панель управления</b>\n👥 Пользователи:\n"
            for u_id, u_name, u_fn, j_date, total, avg_ats in users:
                msg += f"• {u_fn or u_name} | Анализов: {total} | Ср. ATS: {avg_ats or 0:.0f}\n"
            send_message(chat_id, msg)
            return 'ok', 200

        # 👁️ АДМИН: ИСТОРИЯ ЮЗЕРА
        if text.startswith('/admin_hist '):
            if chat_id not in ADMIN_IDS: return 'ok', 200
            target_id = text.split()[1]
            hist = get_user_history(int(target_id), 5)
            if not hist:
                send_message(chat_id, f"🔍 У пользователя {target_id} нет анализов.")
                return 'ok', 200
            msg = f"📋 История пользователя {target_id}\n\n"
            for date, ats, ov, typ in hist:
                msg += f"📅 {date[:10]} | ATS: {ats} | Общая: {ov}\n"
            send_message(chat_id, msg)
            return 'ok', 200

        # 📄 ЗАГРУЗКА
        if text in ['📄 Загрузить резюме', '📄 Новое резюме']:
            resume_cache[f"{chat_id}_mode"] = None
            send_message(chat_id, "📎 Отправь PDF (до 10 МБ)")
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
            rtext = extract_text_from_pdf(requests.get(f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{finfo['result']['file_path']}", timeout=60).content)
            if not rtext or len(rtext.split()) < 50:
                send_message(chat_id, "❌ Текст не извлечён")
                return 'ok', 200
            resume_cache[chat_id] = rtext
            resume_cache[f"{chat_id}_mode"] = None
            show_analysis_menu(chat_id)
            return 'ok', 200

        # 🎯 СРАВНЕНИЕ С ВАКАНСИЕЙ
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
Резюме:\n{rtext[:2000]}\nВакансия:\n{job_desc}"""
            res = analyze_part("", "custom", custom_prompt=prompt, timeout=40)
            d = extract_json(res)
            if d and isinstance(d, dict):
                out = (f"🎯 <b>СОВПАДЕНИЕ</b>\n📊 {d.get('match_percent','?')}/100 {get_score_emoji(d.get('match_percent',0))}\n\n"
                       f"❌ <b>Не хватает</b>:\n" + "\n".join(f"• {s}" for s in d.get('missing_skills', [])) + "\n\n"
                       f"💡 <b>Что добавить</b>:\n" + "\n".join(f"• {r}" for r in d.get('recommendations', [])))
            else:
                out = f"🎯 Анализ: {res}"
            send_message(chat_id, out)
            resume_cache[f"{chat_id}_mode"] = None
            return 'ok', 200

        # 🔄 УЛУЧШИТЬ ПУНКТ
        if text == '🔄 Улучшить пункт':
            resume_cache[f"{chat_id}_mode"] = "improve"
            send_message(chat_id, "✍️ Напиши текст, который хочешь переписать.")
            return 'ok', 200

        if resume_cache.get(f"{chat_id}_mode") == "improve":
            rtext = resume_cache.get(chat_id)
            if not rtext: return 'ok', 200
            send_message(chat_id, "✍️ Переписываю... ⏳")
            prompt = f"Перепиши этот фрагмент идеально. Добавь цифры, убери воду. Только текст.\nФрагмент:\n{text}\nКонтекст:\n{rtext[:2000]}"
            send_message(chat_id, analyze_part("", "custom", custom_prompt=prompt, timeout=40))
            resume_cache[f"{chat_id}_mode"] = None
            return 'ok', 200

        # 📤 СКАЧАТЬ ОТЧЁТ
        if text == '📤 Скачать отчёт':
            rtext = resume_cache.get(chat_id)
            if not rtext:
                send_message(chat_id, "❌ Сначала загрузи резюме")
                return 'ok', 200
            report = f"📊 ОТЧЁТ — {datetime.now().strftime('%d.%m.%Y')}\n\n{rtext[:1000]}...\n\n💡 Полный анализ: https://t.me/ResumeEasyBot"
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendDocument"
            file = io.BytesIO(report.encode('utf-8'))
            file.name = f"resume_{chat_id}.txt"
            try:
                requests.post(url, files={"document": (file.name, file, "text/plain")}, data={"chat_id": chat_id, "caption": "📄 Твой отчёт"}, timeout=30)
                send_message(chat_id, "✅ Файл отправлен!")
            except Exception as e:
                send_message(chat_id, f"❌ Ошибка: {e}")
            return 'ok', 200

        # 🧠 АНАЛИЗ
        PART_MAP = {
            '🤖 ATS-рубрика': 'ats_score', '💪 Сильные стороны': 'strengths',
            '⚠️ Слабые стороны': 'weaknesses', '🔑 Ключевые слова': 'keywords',
            '💡 Советы (Было→Стало)': 'recommendations', '🎯 Вердикт': 'final_verdict',
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
            
            # Сохраняем в БД
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

        # 🚀 ПОЛНЫЙ РАЗБОР
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

            ats_block = (f"🤖 <b>ATS</b>\n📞 {d.get('contacts','?')} | 📐 {d.get('structure','?')} | 🔑 {d.get('keywords','?')}\n"
                         f"📊 {d.get('achievements','?')} | 📝 {d.get('format','?')} | 🎯 <b>{d.get('overall','?')}/100</b> {get_level(d.get('overall',0))}\n\n") if d else f"🤖 ATS: {ats_r}\n\n"
            
            send_message(chat_id, f"📊 <b>ОЦЕНКА</b>\n\n{ats_block}📈 Общая: {ov_r}")
            send_message(chat_id, f"💪 <b>СИЛЬНЫЕ</b>:\n{str_r}\n\n⚠️ <b>СЛАБЫЕ</b>:\n{weak_r}")
            send_message(chat_id, f"💡 <b>СОВЕТЫ</b>:\n{rec_r}\n\n✅ Готово! Уровень: {get_level(ats_val)}")
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
