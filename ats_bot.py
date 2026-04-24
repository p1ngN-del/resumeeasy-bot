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
analysis_cache = {}

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

def analyze_part(resume_text, part_name):
    url = "https://api.deepseek.com/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json"
    }

    prompts = {
        "ats_score": f"Оцени ATS-совместимость резюме от 0 до 100. Ответь ТОЛЬКО числом. БЕЗ ТЕКСТА.\n\nРезюме:\n{resume_text[:4000]}",
        "overall_score": f"Оцени общее качество резюме от 0 до 100. Ответь ТОЛЬКО числом.\n\nРезюме:\n{resume_text[:4000]}",
        "strengths": f"Выдели 5-7 сильных сторон этого резюме. Используй эмодзи. БЕЗ ЗВЁЗДОЧЕК.\n\nРезюме:\n{resume_text[:4000]}",
        "weaknesses": f"Выдели 5-7 слабых сторон и ошибок в этом резюме. Используй эмодзи. БЕЗ ЗВЁЗДОЧЕК.\n\nРезюме:\n{resume_text[:4000]}",
        "keywords": f"Выдай 8-12 ключевых слов для ATS через запятую. ТОЛЬКО слова.\n\nРезюме:\n{resume_text[:4000]}",
        "recommendations": f"Дай 5-7 конкретных рекомендаций по улучшению резюме. Используй эмодзи.\n\nРезюме:\n{resume_text[:4000]}",
        "final_verdict": f"Дай финальный вердикт: готово к рассылке (Да/Нет), топ-3 критических исправления, прогноз конверсии в %. Используй эмодзи.\n\nРезюме:\n{resume_text[:4000]}",
        "rewrite": f"Перепиши резюме полностью в идеальном варианте. Сделай его сильным, с цифрами и конкретикой. Убери всю воду. Используй глаголы действия. БЕЗ ЗВЁЗДОЧЕК. Только plain text.\n\nОригинал:\n{resume_text[:4000]}"
    }

    payload = {
        "model": "deepseek-chat",
        "messages": [{"role": "user", "content": prompts[part_name]}],
        "temperature": 0,
        "max_tokens": 2000
    }

    response = requests.post(url, headers=headers, json=payload, timeout=120)
    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"].strip()

def get_score_emoji(score):
    if score >= 90:
        return "🟢"
    elif score >= 70:
        return "🟡"
    elif score >= 50:
        return "🟠"
    else:
        return "🔴"

def show_welcome_menu(chat_id):
    keyboard = {
        "keyboard": [
            ["📄 Загрузить резюме"],
            ["❓ Помощь", "📊 Моя статистика"]
        ],
        "resize_keyboard": True
    }
    send_message(chat_id, 
        "✨ <b>ResumeEasy Bot</b> ✨\n\n"
        "📄 <b>Ваш личный ATS-эксперт</b>\n"
        "Анализирую резюме по стандартам hh.ru 2026\n\n"
        "🚀 <b>Нажмите «Загрузить резюме»</b>\n"
        "и отправьте PDF-файл\n\n"
        "⏳ Анализ занимает 30-60 секунд",
        reply_markup=keyboard)

def show_analysis_menu(chat_id):
    keyboard = {
        "keyboard": [
            ["🤖 ATS-оценка", "📊 Общая оценка"],
            ["💪 Сильные стороны", "⚠️ Слабые стороны"],
            ["🔑 Ключевые слова", "💡 Рекомендации"],
            ["🎯 Финальный вердикт", "✨ Переделать резюме"],
            ["📄 Загрузить другое", "🏠 Главное меню"]
        ],
        "resize_keyboard": True
    }
    send_message(chat_id, 
        "✅ <b>Резюме загружено!</b>\n\n"
        "🎯 <b>Выберите, что хотите получить:</b>\n\n"
        "🤖 ATS-оценка — насколько резюме дружит с парсерами\n"
        "📊 Общая оценка — качество контента\n"
        "💪 Сильные стороны — что уже работает\n"
        "⚠️ Слабые стороны — что нужно срочно исправить\n"
        "🔑 Ключевые слова — для прохода фильтров\n"
        "💡 Рекомендации — конкретные шаги\n"
        "🎯 Финальный вердикт — готовность к рассылке\n"
        "✨ Переделать резюме — идеальная версия",
        reply_markup=keyboard)

@app.route('/webhook', methods=['POST'])
def webhook():
    global resume_cache, analysis_cache
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

        # Админ-команда
        if text == '/admin':
            total_users, total_analyses, avg_ats, avg_overall = get_all_stats()
            send_message(chat_id, 
                f"📊 <b>СТАТИСТИКА БОТА</b> 📊\n\n"
                f"👥 Всего пользователей: {total_users}\n"
                f"📄 Всего анализов: {total_analyses}\n"
                f"📈 Средний ATS-балл: {avg_ats:.1f}/100\n"
                f"📈 Средняя общая оценка: {avg_overall:.1f}/100\n\n"
                f"📅 {datetime.now().strftime('%d.%m.%Y %H:%M')}")
            return 'ok', 200

        # Главное меню
        if text == '/start' or text == '🏠 Главное меню':
            show_welcome_menu(chat_id)
            return 'ok', 200

        if text == '❓ Помощь':
            send_message(chat_id, 
                "📘 <b>Как пользоваться ботом</b> 📘\n\n"
                "1️⃣ Нажмите «Загрузить резюме»\n"
                "2️⃣ Отправьте PDF-файл\n"
                "3️⃣ Дождитесь анализа (30-60 секунд)\n\n"
                "📊 <b>Что вы получите:</b>\n"
                "• ATS-оценка (0-100)\n"
                "• Общая оценка резюме\n"
                "• Сильные и слабые стороны\n"
                "• Ключевые слова для ATS\n"
                "• Рекомендации\n"
                "• Финальный вердикт\n"
                "• Идеальная версия резюме")
            return 'ok', 200

        if text == '📊 Моя статистика':
            total_analyses, avg_ats, avg_overall = get_user_stats(chat_id)
            emoji_ats = get_score_emoji(avg_ats)
            emoji_overall = get_score_emoji(avg_overall)
            send_message(chat_id, 
                f"📊 <b>ВАША СТАТИСТИКА</b> 📊\n\n"
                f"📄 Анализов проведено: {total_analyses}\n"
                f"{emoji_ats} Средний ATS-балл: {avg_ats:.1f}/100\n"
                f"{emoji_overall} Средняя общая оценка: {avg_overall:.1f}/100")
            return 'ok', 200

        if text == '📄 Загрузить резюме' or text == '📄 Загрузить другое':
            send_message(chat_id, "📎 Отправьте PDF-файл с резюме.\n\n🔄 Начну анализ сразу после получения файла...")
            return 'ok', 200

        # Обработка кнопок анализа
        if text in ['🤖 ATS-оценка', '📊 Общая оценка', '💪 Сильные стороны', '⚠️ Слабые стороны', '🔑 Ключевые слова', '💡 Рекомендации', '🎯 Финальный вердикт', '✨ Переделать резюме']:
            resume_text = resume_cache.get(chat_id)
            if not resume_text:
                show_welcome_menu(chat_id)
                send_message(chat_id, "❌ Сессия истекла. Загрузите резюме заново.")
                return 'ok', 200

            # Маппинг кнопок на функции
            if text == '🤖 ATS-оценка':
                result = analyze_part(resume_text, "ats_score")
                try:
                    score = int(result)
                    emoji = get_score_emoji(score)
                    send_message(chat_id, f"{emoji} <b>ATS-оценка: {score}/100</b>")
                except:
                    send_message(chat_id, f"🤖 <b>ATS-оценка</b>\n\n{result}")

            elif text == '📊 Общая оценка':
                result = analyze_part(resume_text, "overall_score")
                try:
                    score = int(result)
                    emoji = get_score_emoji(score)
                    send_message(chat_id, f"{emoji} <b>Общая оценка: {score}/100</b>")
                except:
                    send_message(chat_id, f"📊 <b>Общая оценка</b>\n\n{result}")

            elif text == '💪 Сильные стороны':
                result = analyze_part(resume_text, "strengths")
                send_message(chat_id, f"💪 <b>СИЛЬНЫЕ СТОРОНЫ</b>\n\n{result}")

            elif text == '⚠️ Слабые стороны':
                result = analyze_part(resume_text, "weaknesses")
                send_message(chat_id, f"⚠️ <b>СЛАБЫЕ СТОРОНЫ</b>\n\n{result}")

            elif text == '🔑 Ключевые слова':
                result = analyze_part(resume_text, "keywords")
                send_message(chat_id, f"🔑 <b>КЛЮЧЕВЫЕ СЛОВА ДЛЯ ATS</b>\n\n{result}")

            elif text == '💡 Рекомендации':
                result = analyze_part(resume_text, "recommendations")
                send_message(chat_id, f"💡 <b>РЕКОМЕНДАЦИИ ПО УЛУЧШЕНИЮ</b>\n\n{result}")

            elif text == '🎯 Финальный вердикт':
                result = analyze_part(resume_text, "final_verdict")
                send_message(chat_id, f"🎯 <b>ФИНАЛЬНЫЙ ВЕРДИКТ</b>\n\n{result}")

            elif text == '✨ Переделать резюме':
                result = analyze_part(resume_text, "rewrite")
                send_message(chat_id, f"✨ <b>ИДЕАЛЬНАЯ ВЕРСИЯ РЕЗЮМЕ</b>\n\n{result}")

            return 'ok', 200

        # Обработка PDF
        if 'document' in data['message']:
            doc = data['message']['document']
            if doc.get('mime_type') != 'application/pdf':
                send_message(chat_id, "❌ Отправьте файл в формате PDF.")
                return 'ok', 200

            send_message(chat_id, "🔍 <b>Получил PDF. Анализирую...</b>\n⏳ 30-60 секунд")

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
            show_analysis_menu(chat_id)
            return 'ok', 200

        return 'ok', 200

    except Exception as e:
        logger.error(f"Webhook error: {e}")
        send_message(chat_id, f"❌ Ошибка: {str(e)[:200]}")
        return 'error', 500

@app.route('/', methods=['GET', 'HEAD'])
def index():
    return 'ResumeEasy Bot is running', 200

if __name__ != "__main__":
    init_db()
    logger.info("ResumeEasy Bot starting...")
