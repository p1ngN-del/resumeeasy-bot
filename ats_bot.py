#!/usr/bin/env python3
import os
import io
import logging
import requests
import sqlite3
import re
from flask import Flask, request
from PyPDF2 import PdfReader
import json
from datetime import datetime

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY")

if not TELEGRAM_TOKEN or not DEEPSEEK_API_KEY:
    raise ValueError("Missing TELEGRAM_TOKEN or DEEPSEEK_API_KEY")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# ===== БАЗА ДАННЫХ =====
DB_NAME = "resumeeasy.db"

def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            join_date TEXT,
            last_activity TEXT
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS analyses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            resume_text TEXT,
            ats_score INTEGER,
            overall_score INTEGER,
            metrics_json TEXT,
            analysis_date TEXT,
            FOREIGN KEY (user_id) REFERENCES users (user_id)
        )
    ''')
    conn.commit()
    conn.close()

def save_user(user_id, username, first_name):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT OR REPLACE INTO users (user_id, username, first_name, join_date, last_activity)
        VALUES (?, ?, ?, COALESCE((SELECT join_date FROM users WHERE user_id = ?), ?), ?)
    ''', (user_id, username, first_name, user_id, datetime.now().isoformat(), datetime.now().isoformat()))
    conn.commit()
    conn.close()

def update_user_activity(user_id):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('UPDATE users SET last_activity = ? WHERE user_id = ?', (datetime.now().isoformat(), user_id))
    conn.commit()
    conn.close()

def save_analysis(user_id, resume_text, ats_score, overall_score, metrics_json):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO analyses (user_id, resume_text, ats_score, overall_score, metrics_json, analysis_date)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (user_id, resume_text[:500], ats_score, overall_score, metrics_json, datetime.now().isoformat()))
    conn.commit()
    conn.close()

def get_user_stats(user_id):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('SELECT COUNT(*) FROM analyses WHERE user_id = ?', (user_id,))
    total_analyses = cursor.fetchone()[0]
    cursor.execute('SELECT AVG(ats_score), AVG(overall_score) FROM analyses WHERE user_id = ?', (user_id,))
    avg_scores = cursor.fetchone()
    conn.close()
    return total_analyses, avg_scores[0] or 0, avg_scores[1] or 0

def get_all_stats():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('SELECT COUNT(*) FROM users')
    total_users = cursor.fetchone()[0]
    cursor.execute('SELECT COUNT(*) FROM analyses')
    total_analyses = cursor.fetchone()[0]
    cursor.execute('SELECT AVG(ats_score) FROM analyses WHERE ats_score > 0')
    avg_ats = cursor.fetchone()[0] or 0
    cursor.execute('SELECT AVG(overall_score) FROM analyses WHERE overall_score > 0')
    avg_overall = cursor.fetchone()[0] or 0
    conn.close()
    return total_users, total_analyses, avg_ats, avg_overall

resume_cache = {}

def send_message(chat_id, text, reply_markup=None):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}
    if reply_markup:
        payload["reply_markup"] = json.dumps(reply_markup)
    try:
        requests.post(url, json=payload, timeout=30)
    except Exception as e:
        logger.error(f"Send error: {e}")

def extract_text_from_pdf(file_bytes):
    try:
        pdf = PdfReader(io.BytesIO(file_bytes))
        text = ""
        for page in pdf.pages:
            page_text = page.extract_text()
            if page_text:
                text += page_text + "\n"
        return text.strip() if text.strip() else None
    except Exception as e:
        logger.error(f"PDF error: {e}")
        return None

def analyze_resume(resume_text):
    url = "https://api.deepseek.com/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json"
    }

    prompt = f"""Ты — старший HR-рекрутер и эксперт по ATS с 10+ лет опыта в России, знакомый с текущими алгоритмами парсинга и требованиями hh.ru (2026).

Проведи глубокий анализ резюме.

ВАЖНЫЕ ПРАВИЛА:
- НЕ ИСПОЛЬЗУЙ звёздочки (*)
- НЕ ИСПОЛЬЗУЙ ### и #
- НЕ ИСПОЛЬЗУЙ жирный шрифт, курсив, таблицы
- Только plain text
- Используй эмодзи и разделители ━━━

Резюме для анализа:
{resume_text[:6000]}

ВЕРНИ ОТВЕТ ТОЧНО В ЭТОМ ФОРМАТЕ:

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1️⃣ ATS-ОЦЕНКА (0-100 баллов)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Оценка: X/100

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
2️⃣ ОБЩАЯ ОЦЕНКА РЕЗЮМЕ (0-100 баллов)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Оценка: X/100

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
3️⃣ СИЛЬНЫЕ СТОРОНЫ
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

- пункт 1
- пункт 2

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
4️⃣ СЛАБЫЕ СТОРОНЫ (ОШИБКИ)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

- пункт 1
- пункт 2

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
5️⃣ 8-12 КЛЮЧЕВЫХ СЛОВ ДЛЯ ATS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

слово1, слово2, слово3...

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
6️⃣ ТОЧЕЧНЫЕ ПРАВКИ (6-10 примеров)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Было: "..."
Стало: "..."

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
7️⃣ РЕКОМЕНДАЦИИ
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

- рекомендация 1
- рекомендация 2

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
8️⃣ ФИНАЛЬНЫЙ ВЕРДИКТ
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Готово к рассылке: Да/Нет
Топ-3 исправления: ...
Прогноз конверсии: X%"""

    payload = {
        "model": "deepseek-chat",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0,
        "max_tokens": 4000
    }

    response = requests.post(url, headers=headers, json=payload, timeout=180)
    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"]

def get_score_emoji(score):
    if score >= 90:
        return "🟢"
    elif score >= 70:
        return "🟡"
    elif score >= 50:
        return "🟠"
    else:
        return "🔴"

def show_main_menu(chat_id):
    keyboard = {
        "keyboard": [
            ["📄 Загрузить резюме"],
            ["❓ Помощь", "📊 Статистика"]
        ],
        "resize_keyboard": True
    }
    send_message(chat_id, 
        "✨ Добро пожаловать в ResumeEasy Bot! ✨\n\n"
        "📄 Я проведу ATS-анализ вашего резюме\n"
        "по стандартам hh.ru 2026.\n\n"
        "🚀 Нажмите «Загрузить резюме» и отправьте PDF!\n"
        "⏳ Анализ занимает 30-60 секунд.")

@app.route('/webhook', methods=['POST'])
def webhook():
    global resume_cache
    try:
        data = request.get_json()
        if 'message' not in data:
            return 'ok', 200

        chat_id = data['message']['chat']['id']
        username = data['message']['from'].get('username', 'unknown')
        first_name = data['message']['from'].get('first_name', '')
        
        save_user(chat_id, username, first_name)
        update_user_activity(chat_id)
        
        text = data['message'].get('text', '')

        if text == '/admin':
            total_users, total_analyses, avg_ats, avg_overall = get_all_stats()
            send_message(chat_id, 
                f"📊 СТАТИСТИКА БОТА 📊\n\n"
                f"👥 Всего пользователей: {total_users}\n"
                f"📄 Всего анализов: {total_analyses}\n"
                f"📈 Средний ATS-балл: {avg_ats:.1f}/100\n"
                f"📈 Средняя общая оценка: {avg_overall:.1f}/100\n\n"
                f"📅 {datetime.now().strftime('%d.%m.%Y %H:%M')}")
            return 'ok', 200

        if text == '/start':
            show_main_menu(chat_id)
            return 'ok', 200

        if text == '❓ Помощь':
            send_message(chat_id, 
                "📘 КАК ПОЛЬЗОВАТЬСЯ БОТОМ 📘\n\n"
                "1️⃣ Нажмите «Загрузить резюме»\n"
                "2️⃣ Отправьте PDF-файл\n"
                "3️⃣ Дождитесь анализа (30-60 секунд)\n\n"
                "📊 ЧТО ВЫ ПОЛУЧИТЕ:\n"
                "• ATS-оценка (0-100)\n"
                "• Общая оценка резюме\n"
                "• Сильные и слабые стороны\n"
                "• Ключевые слова для ATS\n"
                "• Точечные правки\n"
                "• Рекомендации\n"
                "• Финальный вердикт\n\n"
                "🔄 Для нового резюме нажмите «Загрузить другое резюме»")
            return 'ok', 200

        if text == '📊 Статистика':
            total_analyses, avg_ats, avg_overall = get_user_stats(chat_id)
            send_message(chat_id, 
                f"📊 ВАША СТАТИСТИКА 📊\n\n"
                f"📄 Всего анализов: {total_analyses}\n"
                f"📈 Средний ATS-балл: {avg_ats:.1f}/100\n"
                f"📈 Средняя общая оценка: {avg_overall:.1f}/100")
            return 'ok', 200

        if text == '🔙 Главное меню':
            show_main_menu(chat_id)
            return 'ok', 200

        if text == '📄 Загрузить резюме' or text == '📄 Загрузить другое резюме':
            send_message(chat_id, "📎 Отправьте PDF-файл с резюме.\n\n🔄 Начну анализ сразу после получения файла...")
            return 'ok', 200

        if text == '📊 Полный ATS-анализ':
            resume_text = resume_cache.get(chat_id)
            if not resume_text:
                show_main_menu(chat_id)
                send_message(chat_id, "❌ Сессия истекла. Загрузите резюме заново.")
                return 'ok', 200

            send_message(chat_id, "🔍 Провожу ATS-анализ...\n⏳ 30-60 секунд")
            
            try:
                analysis = analyze_resume(resume_text)
                
                if len(analysis) > 4096:
                    for i in range(0, len(analysis), 4096):
                        send_message(chat_id, analysis[i:i+4096])
                else:
                    send_message(chat_id, analysis)
                    
            except Exception as e:
                logger.error(f"Analysis error: {e}")
                send_message(chat_id, f"❌ Ошибка анализа: {str(e)[:200]}")
            
            return 'ok', 200

        if 'document' in data['message']:
            doc = data['message']['document']
            if doc.get('mime_type') != 'application/pdf':
                send_message(chat_id, "❌ Отправьте PDF файл.")
                return 'ok', 200

            send_message(chat_id, "🔍 Получил PDF. Анализирую...\n⏳ 30-60 секунд")

            file_id = doc['file_id']
            file_info = requests.get(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getFile?file_id={file_id}").json()
            file_path = file_info['result']['file_path']
            file_url = f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{file_path}"
            file_content = requests.get(file_url, timeout=60).content

            resume_text = extract_text_from_pdf(file_content)
            if not resume_text or len(resume_text.split()) < 50:
                send_message(chat_id, "❌ Не удалось извлечь текст из PDF. Убедитесь, что файл не отсканирован.")
                return 'ok', 200

            resume_cache[chat_id] = resume_text

            keyboard = {
                "keyboard": [
                    ["📊 Полный ATS-анализ"],
                    ["📄 Загрузить другое резюме", "🔙 Главное меню"]
                ],
                "resize_keyboard": True
            }

            send_message(chat_id, "✅ Резюме загружено!\n\nНажмите «Полный ATS-анализ» для детального разбора.", reply_markup=keyboard)
            return 'ok', 200

        return 'ok', 200

    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return 'error', 500

@app.route('/', methods=['GET', 'HEAD'])
def index():
    return 'ResumeEasy Bot is running', 200

if __name__ != "__main__":
    init_db()
    logger.info("ResumeEasy Bot starting...")
