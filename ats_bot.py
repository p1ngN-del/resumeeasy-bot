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

Проведи анализ резюме, используя ТОЛЬКО информацию из двух статей, которые я тебе прислал. Ничего не выдумывай от себя.

ВАЖНЫЕ ПРАВИЛА hh.ru:
- На hh.ru НЕЛЬЗЯ использовать жирный шрифт, курсив, подчёркивания, таблицы, колонки, графику, иконки
- Только plain text
- НЕ ИСПОЛЬЗУЙ звёздочки (*) в ответе

Выполни анализ по следующим пунктам (все пункты взяты из статей):

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1️⃣ ЧТО НЕ ТАК С РЕЗЮМЕ (ошибки из статьи)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Проверь наличие этих ошибок (первая статья):

- Нерелевантный опыт (опыт не по специальности)
- Стажировки и курсы в разделе "Опыт работы"
- Резюме-статья (слишком длинное, более 2 страниц)
- Резюме-океан (вода, пустота, нет конкретики)
- Резюме-перекати-поле (слишком пустое, не за что зацепиться)
- Софт скиллы списком ("коммуникабельный, ответственный")
- Очень много непонятных слов и сокращений
- Перегруз сложными терминами
- Нет краткого описания проекта и компании
- Указан региональный город (а не Москва/СПб)
- Оценочные выражения без доказательств ("невероятно быстро", "лучше всех")
- В разделе "О себе" не про работу

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
2️⃣ ATS-ОЦЕНКА (из второй статьи)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Оцени, как резюме пройдёт AI-фильтры (вторая статья):

- Использует ли резюме точные ключевые слова из вакансии?
- Есть ли конкретные названия технологий и инструментов?
- Резюме адаптировано под конкретную вакансию или универсальное?
- Есть ли цифры и измеримые результаты?
- Нужно ли создать 2-3 версии резюме под разные вакансии?

Итоговая ATS-оценка: X/100

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
3️⃣ ДЕТАЛЬНЫЙ РАЗБОР (по статьям)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

По первой статье:

1. Сильные стороны резюме (что хорошо)
2. Слабые стороны резюме (какие ошибки из списка выше)

По второй статье:

3. Какие ключевые слова из вакансий отсутствуют?
4. Какие навыки нужно добавить?

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
4️⃣ КЛЮЧЕВЫЕ СЛОВА (из второй статьи)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Выдели 8-12 ключевых слов/фраз, которые нужно добавить в резюме.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
5️⃣ ТОЧЕЧНЫЕ ПРАВКИ (из первой статьи)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Исправь ошибки из статьи в формате:

Было: "коммуникабельный, ответственный"
Стало: (убрать, заменить на факты)

Было: "фиксил баги, делал фичи"
Стало: "Исправил 50+ критических багов, сократив время отката на 40%"

Было: вода и сложные слова
Стало: сухие фразы и глаголы

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
6️⃣ РЕКОМЕНДАЦИИ ПО ЗАГРУЗКЕ НА hh.ru (из статей)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Из первой статьи:
- Ставь большой город (Москва/СПб) для удалёнки
- Пиши сопроводительное письмо (2-3 предложения о себе под вакансию)

Из второй статьи:
- Используй точные слова из вакансии, не придумывай синонимы
- Добавляй цифры и измеримые результаты
- Создай 2-3 версии резюме под разные типы вакансий
- Обновляй резюме регулярно

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
7️⃣ ПОЧЕМУ ТАК ВАЖНО (из статей)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Из первой статьи: "Резюме — это обложка и краткий пересказ твоего опыта, первое касание с работодателем, которое должно зацепить его, чтобы он захотел с тобой пообщаться. Сильное резюме — это продающий текст, который полностью раскрывает твой опыт и достижения."

Из второй статьи: "До 75% откликов на крупных платформах вроде HeadHunter отсеиваются автоматически, ещё до того, как их увидит живой человек. ATS сканирует резюме по ключевым словам из вакансии. Каждый отклик получает скрытый рейтинг совпадения. Рекрутер видит кандидатов отсортированными по рейтингу. Низкий рейтинг = ваш отклик в конце списка."

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
8️⃣ ФИНАЛЬНЫЙ ВЕРДИКТ (из статей)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

- Готово ли резюме к рассылке? (из первой статьи: ответь себе честно "Ты бы себя нанял?")
- Топ-3 главные ошибки, которые нужно исправить
- Прогноз: (из второй статьи) какой процент совпадения с целевой вакансией?

Резюме для анализа:
{resume_text[:6000]}"""

    payload = {
        "model": "deepseek-chat",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0,
        "max_tokens": 4500
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
                "• Список ошибок из резюме\n"
                "• ATS-оценка (0-100)\n"
                "• Детальный разбор по статьям\n"
                "• Ключевые слова для добавления\n"
                "• Точечные правки\n"
                "• Рекомендации по загрузке на hh.ru\n"
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

            send_message(chat_id, "🔍 Провожу ATS-анализ по вашим статьям...\n⏳ 30-60 секунд")
            
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
    logger.info("ResumeEasy Bot starting with articles-based analysis...")
