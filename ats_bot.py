#!/usr/bin/env python3
import os
import io
import logging
import requests
from flask import Flask, request
from PyPDF2 import PdfReader
import json

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY")

if not TELEGRAM_TOKEN or not DEEPSEEK_API_KEY:
    raise ValueError("Missing TELEGRAM_TOKEN or DEEPSEEK_API_KEY")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Статистика для админа (простая, в памяти)
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

def analyze_with_deepseek(resume_text):
    url = "https://api.deepseek.com/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json"
    }

    prompt = f"""Ты — старший HR-рекрутер и эксперт по ATS. Проанализируй резюме и ВЕРНИ ОТВЕТ ТОЛЬКО В УКАЗАННОМ НИЖЕ ФОРМАТЕ (строго соблюдай структуру). НЕ ИСПОЛЬЗУЙ ЗВЁЗДОЧКИ (*) ДЛЯ ВЫДЕЛЕНИЯ, используй эмодзи и HTML-теги <b>текст</b> для жирного.

Резюме:
{resume_text[:8000]}

ФОРМАТ ОТВЕТА:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🎯 <b>ОБЩАЯ ОЦЕНКА РЕЗЮМЕ</b>
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

<b>Match Score:</b> X/100 🟡/🟢/🔴
<b>Краткий вердикт:</b> ... (1 предложение)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📊 <b>ДЕТАЛЬНЫЙ РАЗБОР ПО МЕТРИКАМ</b>
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

<b>1. Ключевые слова:</b> X/100 🟢/🟡/🔴
<b>2. Достижения (цифры):</b> X/100
<b>3. Форматирование:</b> X/100
<b>4. Длина резюме:</b> X/100
<b>5. Навыки (hard skills):</b> X/100
<b>6. Грамматика и стиль:</b> X/100

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📄 <b>ГОТОВАЯ ВЕРСИЯ ДЛЯ hh.ru</b>
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

(текст в plain text)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🔑 <b>КЛЮЧЕВЫЕ СЛОВА (ATS-READY)</b>
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

• Слово 1
• Слово 2
...

<b>Варианты заголовка резюме:</b>
1. ...
2. ...
3. ...

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
✏️ <b>ТОЧЕЧНЫЕ ПРАВКИ (6-10)</b>
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

<b>Исходный пункт</b> → <b>Исправленный пункт</b>

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
💡 <b>РЕКОМЕНДАЦИИ ПО ЗАГРУЗКЕ НА hh.ru</b>
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

• ...

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
✅ <b>ФИНАЛЬНАЯ ВЕРСИЯ РЕЗЮМЕ</b>
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

(текст в plain text)"""

    payload = {
        "model": "deepseek-chat",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.3,
        "max_tokens": 4000
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

        # Команда для админа
        if 'text' in data['message'] and data['message']['text'] == '/admin':
            send_message(chat_id,
                f"📊 <b>Статистика бота</b>\n\n"
                f"👥 Уникальных пользователей: {len(stats['users'])}\n"
                f"📩 Всего запросов: {stats['total_requests']}")
            return 'ok', 200

        # Обработка /start с кнопками
        if 'text' in data['message'] and data['message']['text'] == '/start':
            keyboard = {
                "keyboard": [["📄 Загрузить резюме"], ["❓ Помощь"]],
                "resize_keyboard": True
            }
            send_message(chat_id,
                "📄 <b>ResumeEasy Bot</b>\n\n"
                "Я проведу полный ATS-анализ вашего резюме по стандартам hh.ru.\n\n"
                "▸ Нажмите <b>«Загрузить резюме»</b> и отправьте PDF-файл.\n"
                "▸ Анализ занимает 20–40 секунд.\n"
                "▸ Результат придёт в виде подробного отчёта.",
                reply_markup=keyboard)
            return 'ok', 200

        # Помощь
        if 'text' in data['message'] and data['message']['text'] == '❓ Помощь':
            send_message(chat_id,
                "📘 <b>Как пользоваться ботом</b>\n\n"
                "1️⃣ Нажмите «Загрузить резюме» и отправьте файл в формате PDF.\n"
                "2️⃣ Дождитесь анализа (20–40 секунд).\n"
                "3️⃣ Получите детальный разбор по 7 блокам:\n"
                "   • Общая оценка (match score)\n"
                "   • Разбор по метрикам (0–100)\n"
                "   • Готовая версия для hh.ru\n"
                "   • Ключевые слова и заголовки\n"
                "   • Точечные правки формулировок\n"
                "   • Рекомендации по загрузке\n"
                "   • Финальная версия резюме")
            return 'ok', 200

        # Обработка PDF
        if 'document' in data['message']:
            doc = data['message']['document']
            if doc.get('mime_type') != 'application/pdf':
                send_message(chat_id, "❌ Пожалуйста, отправьте файл в формате PDF.")
                return 'ok', 200

            send_message(chat_id, "🔍 <b>Анализирую резюме...</b>\nЭто может занять 20–40 секунд.")

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
            analysis = analyze_with_deepseek(resume_text)

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
