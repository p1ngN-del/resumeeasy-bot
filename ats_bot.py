#!/usr/bin/env python3
import os
import io
import logging
import requests
import sqlite3
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

def send_message(chat_id, text, reply_markup=None, parse_mode=None):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}
    if parse_mode:
        payload["parse_mode"] = parse_mode
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
        "ats_score": f"Оцени общий балл ATS резюме от 0 до 100. Ответь ТОЛЬКО числом. БЕЗ ТЕКСТА. БЕЗ ЗВЁЗДОЧЕК. ШКАЛА: каждый балл важен.\n\nРезюме:\n{resume_text[:4000]}",
        "overall_score": f"Оцени общее качество резюме от 0 до 100. Ответь ТОЛЬКО числом. БЕЗ ТЕКСТА. БЕЗ ЗВЁЗДОЧЕК. ШКАЛА: каждый балл важен.\n\nРезюме:\n{resume_text[:4000]}",
        "metrics_with_fixes": f"""Оцени 6 метрик резюме от 0 до 100 (каждый балл важен). Для каждой метрики напиши оценку и конкретную рекомендацию.

Метрики:
1. Ключевые слова
2. Достижения с цифрами
3. Форматирование
4. Длина резюме
5. Навыки (hard skills)
6. Грамматика и стиль

ФОРМАТ ОТВЕТА (без звёздочек):
Метрика: X/100
Рекомендация: текст рекомендации

Резюме:
{resume_text[:4000]}""",
        "final_version": f"Напиши финальную версию резюме в plain text. БЕЗ ЗВЁЗДОЧЕК.\n\nРезюме:\n{resume_text[:4000]}"
    }

    payload = {
        "model": "deepseek-chat",
        "messages": [{"role": "user", "content": prompts[part_name]}],
        "temperature": 0,
        "max_tokens": 2500
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

def parse_metrics_result(result):
    lines = result.strip().split('\n')
    scores = []
    recommendations = []
    for line in lines:
        if 'Метрика:' in line or line.startswith('Метрика'):
            import re
            numbers = re.findall(r'\d+', line)
            if numbers:
                scores.append(int(numbers[0]))
        elif 'Рекомендация:' in line or 'рекомендация' in line.lower():
            if ':' in line:
                recommendations.append(line.split(':', 1)[1].strip())
            else:
                recommendations.append(line)
    return scores, recommendations

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
        "📄 Я помогу вам проанализировать резюме по стандартам ATS и hh.ru 2026.\n\n"
        "🔍 Что я умею:\n"
        "• Оцениваю ATS-совместимость (0-100 баллов)\n"
        "• Анализирую общее качество резюме\n"
        "• Разбираю 6 ключевых метрик с рекомендациями\n"
        "• Составляю финальную версию резюме\n\n"
        "🚀 Нажмите «Загрузить резюме» и отправьте PDF-файл!\n"
        "⏳ Анализ занимает 20-40 секунд.",
        reply_markup=keyboard)

def show_loading_animation(chat_id):
    import time
    for i in range(3):
        dots = '.' * (i + 1)
        send_message(chat_id, f"🔍 Анализирую резюме{dots}\n⏳ Подождите, это займёт 20-40 секунд...")
        time.sleep(2)

def format_metrics_response(scores, recommendations):
    if not scores or len(scores) < 6:
        return "Не удалось получить разбор метрик. Попробуйте ещё раз."
    
    metric_names = [
        "Ключевые слова",
        "Достижения с цифрами",
        "Форматирование",
        "Длина резюме",
        "Навыки (hard skills)",
        "Грамматика и стиль"
    ]
    
    response = "📊 Детальный разбор по 6 метрикам\n\n"
    for i, name in enumerate(metric_names):
        if i < len(scores):
            emoji = get_score_emoji(scores[i])
            response += f"{emoji} {name}: {scores[i]}/100\n"
            if i < len(recommendations):
                response += f"   ➜ Рекомендация: {recommendations[i]}\n\n"
            else:
                response += "\n"
    return response

@app.route('/webhook', methods=['POST'])
def webhook():
    global stats, resume_cache
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
                f"📅 Данные на {datetime.now().strftime('%d.%m.%Y %H:%M')}")
            return 'ok', 200

        if text == '/start':
            show_main_menu(chat_id)
            return 'ok', 200

        if text == '❓ Помощь':
            send_message(chat_id, 
                "📘 КАК ПОЛЬЗОВАТЬСЯ БОТОМ\n\n"
                "1️⃣ Нажмите «Загрузить резюме»\n"
                "2️⃣ Отправьте PDF-файл\n"
                "3️⃣ Дождитесь анализа (20-40 секунд)\n\n"
                "📊 ЧТО ВЫ ПОЛУЧИТЕ:\n"
                "• Общий балл ATS (0-100) с цветовой индикацией\n"
                "• Общую оценку резюме (0-100)\n"
                "• Детальный разбор по 6 метрикам с рекомендациями\n"
                "• Финальную версию резюме\n\n"
                "🔄 Для нового резюме нажмите «Загрузить другое резюме»\n"
                "🔙 Для возврата в главное меню нажмите «Главное меню»")
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
            send_message(chat_id, "📎 Отправьте PDF-файл с резюме.\n\n🔄 Я начну анализ сразу после получения файла.")
            return 'ok', 200

        if text in ['📊 Общий балл ATS', '📈 Общая оценка резюме', '🔍 Детальный разбор с рекомендациями', '✅ Финальная версия резюме']:
            resume_text = resume_cache.get(chat_id)
            if not resume_text:
                show_main_menu(chat_id)
                send_message(chat_id, "❌ Сессия истекла. Загрузите резюме заново.")
                return 'ok', 200

            if text == '📊 Общий балл ATS':
                score = analyze_part(resume_text, "ats_score")
                try:
                    score_int = int(score.split()[0] if ' ' in score else score)
                    send_message(chat_id, f"{get_score_emoji(score_int)} Общий балл ATS: {score_int}/100")
                except:
                    send_message(chat_id, f"Общий балл ATS: {score}")

            elif text == '📈 Общая оценка резюме':
                score = analyze_part(resume_text, "overall_score")
                try:
                    score_int = int(score.split()[0] if ' ' in score else score)
                    send_message(chat_id, f"{get_score_emoji(score_int)} Общая оценка резюме: {score_int}/100")
                except:
                    send_message(chat_id, f"Общая оценка: {score}")

            elif text == '🔍 Детальный разбор с рекомендациями':
                result = analyze_part(resume_text, "metrics_with_fixes")
                scores, recommendations = parse_metrics_result(result)
                formatted = format_metrics_response(scores, recommendations)
                send_message(chat_id, formatted)

            elif text == '✅ Финальная версия резюме':
                result = analyze_part(resume_text, "final_version")
                send_message(chat_id, f"✅ ФИНАЛЬНАЯ ВЕРСИЯ РЕЗЮМЕ ✅\n\n{result}")

            return 'ok', 200

        if 'document' in data['message']:
            doc = data['message']['document']
            if doc.get('mime_type') != 'application/pdf':
                send_message(chat_id, "❌ Отправьте PDF файл.")
                return 'ok', 200

            send_message(chat_id, "🔍 Анализирую резюме...\n⏳ Подождите, это займёт 20-40 секунд...")

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
            
            ats_score = 0
            overall_score = 0
            try:
                ats_score = int(analyze_part(resume_text, "ats_score").split()[0])
                overall_score = int(analyze_part(resume_text, "overall_score").split()[0])
            except:
                pass
            
            metrics_result = analyze_part(resume_text, "metrics_with_fixes")
            save_analysis(chat_id, resume_text, ats_score, overall_score, metrics_result)

            keyboard = {
                "keyboard": [
                    ["📊 Общий балл ATS", "📈 Общая оценка резюме"],
                    ["🔍 Детальный разбор с рекомендациями"],
                    ["✅ Финальная версия резюме"],
                    ["📄 Загрузить другое резюме", "🔙 Главное меню"]
                ],
                "resize_keyboard": True
            }

            send_message(chat_id, "✅ Резюме загружено!\n\nВыберите, что хотите получить:", reply_markup=keyboard)
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
    logger.info("ResumeEasy Bot starting with persistent database...")
