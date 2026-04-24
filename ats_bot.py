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

# Статистика для админа
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

    prompt = f"""Ты — эксперт по ATS с 10+ лет опыта. Проанализируй резюме и ВЕРНИ ОТВЕТ ТОЛЬКО В ФОРМАТЕ, УКАЗАННОМ НИЖЕ. НЕ ПРОПУСКАЙ НИ ОДИН ПУНКТ. НЕ СОКРАЩАЙ.

Резюме:
{resume_text[:6000]}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📊 ФОРМАТ ОТВЕТА (строго соблюдай)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

1️⃣ <b>ОБЩАЯ ОЦЕНКА РЕЗЮМЕ (ATS SCORE)</b>
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

<b>Общий балл ATS:</b> X/100

Где:
90-100 — 🟢 Отлично, резюме готово
70-89 — 🟡 Хорошо, но есть недочёты
50-69 — 🟠 Средне, требуются улучшения
0-49 — 🔴 Плохо, нужна полная переработка

<b>Краткий вердикт:</b> (1-2 предложения)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
2️⃣ <b>ДЕТАЛЬНЫЙ РАЗБОР ПО МЕТРИКАМ</b>
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

<b>1. Ключевые слова под профессию:</b> X/100
<b>2. Достижения (цифры, результаты):</b> X/100
<b>3. Форматирование (читаемость для ATS):</b> X/100
<b>4. Длина резюме (1-2 страницы):</b> X/100
<b>5. Навыки (hard skills):</b> X/100
<b>6. Грамматика и стиль:</b> X/100

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
3️⃣ <b>ГОТОВАЯ ВЕРСИЯ ДЛЯ hh.ru</b>
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

(текст в plain text, обратная хронология, 2-4 достижения на место с цифрами)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
4️⃣ <b>КЛЮЧЕВЫЕ СЛОВА ATS-READY</b>
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

<u>8-12 ключевых слов:</u> слово1, слово2, слово3, слово4, слово5...

<u>3 варианта заголовка резюме:</u>
1. ...
2. ...
3. ...

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
5️⃣ <b>ТОЧЕЧНЫЕ ПРАВКИ (6-10 пунктов)</b>
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

<b>Было:</b> «...»
<b>Стало:</b> «...»

(повторить 6-10 раз)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
6️⃣ <b>РЕКОМЕНДАЦИИ ПО ЗАГРУЗКЕ НА hh.ru</b>
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

• Поля: заголовок, зарплата, релокация
• Фильтры и категории
• Как вставить ссылки
• Портфолио и проекты

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
7️⃣ <b>ФИНАЛЬНАЯ ВЕРСИЯ РЕЗЮМЕ (PLAIN TEXT)</b>
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

(текст без форматирования, готовый для копирования)

📌 ВАЖНО: ВСЕ 7 ПУНКТОВ ДОЛЖНЫ БЫТЬ В ОТВЕТЕ. НЕ ПРОПУСКАЙ. НЕ СОКРАЩАЙ."""

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

        # Скрытая админ-команда
        if text == '/admin':
            send_message(chat_id,
                f"📊 <b>Статистика бота</b>\n\n"
                f"👥 Пользователей: {len(stats['users'])}\n"
                f"📩 Запросов: {stats['total_requests']}")
            return 'ok', 200

        # Команда /start с меню
        if text == '/start':
            keyboard = {
                "keyboard": [
                    ["📄 Загрузить резюме", "❓ Помощь"],
                    ["📊 Моя статистика", "👤 Профиль"]
                ],
                "resize_keyboard": True
            }
            send_message(chat_id,
                "📄 <b>ResumeEasy Bot</b>\n\n"
                "Я проведу полный ATS-анализ вашего резюме и дам <b>бальную оценку от 0 до 100</b>.\n\n"
                "▸ Нажмите <b>«Загрузить резюме»</b> и отправьте PDF.\n"
                "▸ Анализ занимает 20–40 секунд.\n"
                "▸ Результат: общий балл + разбор по 6 метрикам + готовая версия для hh.ru.",
                reply_markup=keyboard)
            return 'ok', 200

        # Обработка кнопок
        if text == '📄 Загрузить резюме':
            send_message(chat_id, "📎 Отправьте PDF-файл с вашим резюме.")
            return 'ok', 200

        if text == '❓ Помощь':
            send_message(chat_id,
                "📘 <b>Как пользоваться ботом</b>\n\n"
                "1️⃣ Нажмите «Загрузить резюме» и отправьте PDF.\n"
                "2️⃣ Дождитесь анализа (20–40 секунд).\n"
                "3️⃣ Получите детальный разбор:\n\n"
                "   • <b>Общий балл ATS</b> (0–100) с цветовой индикацией\n"
                "   • <b>6 метрик</b> (каждая с оценкой 0–100)\n"
                "   • Готовую версию для hh.ru\n"
                "   • Ключевые слова и заголовки\n"
                "   • Точечные правки\n"
                "   • Рекомендации по загрузке\n"
                "   • Финальную версию")
            return 'ok', 200

        if text == '📊 Моя статистика':
            send_message(chat_id,
                f"📈 <b>Ваша активность</b>\n\n"
                f"📄 Всего анализов: {stats['total_requests']}\n"
                f"👤 ID пользователя: <code>{chat_id}</code>")
            return 'ok', 200

        if text == '👤 Профиль':
            send_message(chat_id,
                f"👤 <b>Ваш профиль</b>\n\n"
                f"🆔 ID: <code>{chat_id}</code>\n"
                f"📅 Активен с: {datetime.now().strftime('%d.%m.%Y')}\n\n"
                f"Для анализа нажмите «Загрузить резюме».")
            return 'ok', 200

        # Обработка PDF
        if 'document' in data['message']:
            doc = data['message']['document']
            if doc.get('mime_type') != 'application/pdf':
                send_message(chat_id, "❌ Пожалуйста, отправьте файл в формате PDF.")
                return 'ok', 200

            send_message(chat_id, "🔍 <b>Анализирую резюме...</b>\n⏳ Это займёт 20–40 секунд.")

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
