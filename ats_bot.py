#!/usr/bin/env python3
import os
import io
import logging
import requests
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
stats = {"users": set(), "total_requests": 0}

def send_message(chat_id, text, reply_markup=None):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
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

    prompt = f"""Ты эксперт по ATS с 10+ лет опыта. Проанализируй резюме и верни ОДИН ЦЕЛЬНЫЙ ОТВЕТ в формате ниже. НЕ ИСПОЛЬЗУЙ ЗВЁЗДОЧКИ. Используй HTML-теги <b>текст</b> для жирного.

Резюме:
{resume_text[:6000]}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1️⃣ ОБЩАЯ ОЦЕНКА РЕЗЮМЕ (ATS SCORE)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

<b>Общий балл ATS:</b> X/100

Где:
90-100 — 🟢 Отлично
70-89 — 🟡 Хорошо
50-69 — 🟠 Средне
0-49 — 🔴 Плохо

<b>Краткий вердикт:</b> (1-2 предложения)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
2️⃣ ДЕТАЛЬНЫЙ РАЗБОР ПО МЕТРИКАМ
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

<b>1. Ключевые слова:</b> X/100
<b>2. Достижения (цифры):</b> X/100
<b>3. Форматирование:</b> X/100
<b>4. Длина резюме:</b> X/100
<b>5. Навыки (hard skills):</b> X/100
<b>6. Грамматика и стиль:</b> X/100

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
3️⃣ ГОТОВАЯ ВЕРСИЯ ДЛЯ hh.ru
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

(текст в plain text, обратная хронология, 2-4 достижения на место с цифрами)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
4️⃣ КЛЮЧЕВЫЕ СЛОВА И ЗАГОЛОВКИ
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

<b>Ключевые слова (8-12):</b> слово1, слово2, слово3...

<b>Варианты заголовка резюме:</b>
1. ...
2. ...
3. ...

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
5️⃣ ТОЧЕЧНЫЕ ПРАВКИ (6-10)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

1. исправление
2. исправление
...

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
6️⃣ РЕКОМЕНДАЦИИ ПО ЗАГРУЗКЕ НА hh.ru
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

1. ...
2. ...
...

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
7️⃣ ФИНАЛЬНАЯ ВЕРСИЯ РЕЗЮМЕ
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

(текст в plain text, готовый для копирования)

ВСЕ 7 ПУНКТОВ ДОЛЖНЫ БЫТЬ В ОТВЕТЕ. НЕ СОКРАЩАЙ. НЕ ПРОПУСКАЙ."""

    payload = {
        "model": "deepseek-chat",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.2,
        "max_tokens": 4500
    }

    response = requests.post(url, headers=headers, json=payload, timeout=180)
    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"]

@app.route('/webhook', methods=['POST'])
def webhook():
    global stats
    try:
        data = request.get_json()
        if 'message' not in data:
            return 'ok', 200

        chat_id = data['message']['chat']['id']
        stats["users"].add(chat_id)
        stats["total_requests"] += 1
        text = data['message'].get('text', '')

        # Админ-команда
        if text == '/admin':
            send_message(chat_id,
                f"📊 <b>Статистика бота</b>\n\n"
                f"👥 Пользователей: {len(stats['users'])}\n"
                f"📩 Запросов: {stats['total_requests']}")
            return 'ok', 200

        # Старт с меню
        if text == '/start':
            keyboard = {
                "keyboard": [["📄 Загрузить резюме"], ["❓ Помощь"]],
                "resize_keyboard": True
            }
            send_message(chat_id,
                "📄 <b>ResumeEasy Bot</b>\n\n"
                "Я проведу полный ATS-анализ вашего резюме и дам <b>бальную оценку от 0 до 100</b>.\n\n"
                "Нажмите «Загрузить резюме» и отправьте PDF.",
                reply_markup=keyboard)
            return 'ok', 200

        if text == '❓ Помощь':
            send_message(chat_id,
                "📘 <b>Как пользоваться ботом</b>\n\n"
                "1️⃣ Нажмите «Загрузить резюме»\n"
                "2️⃣ Отправьте PDF-файл\n"
                "3️⃣ Дождитесь анализа (20-40 секунд)\n\n"
                "📊 <b>Что вы получите:</b>\n"
                "• Общий балл ATS (0-100)\n"
                "• Разбор по 6 метрикам\n"
                "• Готовую версию для hh.ru\n"
                "• Ключевые слова и заголовки\n"
                "• Точечные правки\n"
                "• Рекомендации\n"
                "• Финальную версию")
            return 'ok', 200

        if text == '📄 Загрузить резюме':
            send_message(chat_id, "📎 Отправьте PDF-файл с резюме.")
            return 'ok', 200

        # Обработка PDF
        if 'document' in data['message']:
            doc = data['message']['document']
            if doc.get('mime_type') != 'application/pdf':
                send_message(chat_id, "❌ Отправьте PDF файл.")
                return 'ok', 200

            send_message(chat_id, "🔍 <b>Анализирую резюме...</b>\n⏳ Это займёт 20-40 секунд.")

            # Скачиваем файл
            file_id = doc['file_id']
            file_info = requests.get(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getFile?file_id={file_id}").json()
            file_path = file_info['result']['file_path']
            file_url = f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{file_path}"
            file_content = requests.get(file_url, timeout=60).content

            # Извлекаем текст
            resume_text = extract_text_from_pdf(file_content)
            if not resume_text or len(resume_text.split()) < 50:
                send_message(chat_id, "❌ Не удалось извлечь текст из PDF. Убедитесь, что файл не отсканирован.")
                return 'ok', 200

            # Анализируем
            analysis = analyze_resume(resume_text)

            # Отправляем результат
            if len(analysis) > 4096:
                for i in range(0, len(analysis), 4096):
                    send_message(chat_id, analysis[i:i+4096])
            else:
                send_message(chat_id, analysis)

            return 'ok', 200

        return 'ok', 200

    except Exception as e:
        logger.error(f"Webhook error: {e}")
        send_message(chat_id, "❌ Произошла ошибка. Попробуйте ещё раз.")
        return 'error', 500

@app.route('/', methods=['GET', 'HEAD'])
def index():
    return 'ResumeEasy Bot is running', 200

if __name__ != "__main__":
    logger.info("ResumeEasy Bot starting...")
