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

# Хранилище для текста резюме по chat_id (временное)
resume_cache = {}

def send_message(chat_id, text, reply_markup=None):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    if reply_markup:
        payload["reply_markup"] = json.dumps(reply_markup)
    try:
        requests.post(url, json=payload, timeout=30)
    except Exception as e:
        logger.error(f"Send error: {e}")

def edit_message(chat_id, message_id, text, reply_markup=None):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/editMessageText"
    payload = {"chat_id": chat_id, "message_id": message_id, "text": text, "parse_mode": "HTML"}
    if reply_markup:
        payload["reply_markup"] = json.dumps(reply_markup)
    try:
        requests.post(url, json=payload, timeout=30)
    except Exception as e:
        logger.error(f"Edit error: {e}")

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

def get_score_emoji(score):
    if score >= 90:
        return "🟢"
    elif score >= 70:
        return "🟡"
    elif score >= 50:
        return "🟠"
    else:
        return "🔴"

def analyze_part(resume_text, part_name):
    url = "https://api.deepseek.com/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json"
    }

    prompts = {
        "ats_score": f"""Ты эксперт по ATS. Проанализируй резюме и ВЕРНИ ТОЛЬКО ЧИСЛО ОТ 0 ДО 100. БЕЗ ТЕКСТА. БЕЗ ОБЪЯСНЕНИЙ.

Резюме:
{resume_text[:4000]}

Оцени общий балл ATS от 0 до 100.""",

        "detailed_metrics": f"""Ты эксперт по ATS. Проанализируй резюме и ВЕРНИ ТОЛЬКО 6 ЧИСЕЛ ЧЕРЕЗ ЗАПЯТУЮ. БЕЗ ТЕКСТА.

Резюме:
{resume_text[:4000]}

Оцени от 0 до 100:
1. Ключевые слова
2. Достижения с цифрами
3. Форматирование
4. Длина резюме
5. Навыки (hard skills)
6. Грамматика и стиль

Пример ответа: 85,70,90,95,80,75""",

        "hh_version": f"""Ты эксперт по ATS. Проанализируй резюме и создай готовую версию для hh.ru в plain text.

Резюме:
{resume_text[:4000]}

Требования:
- обратная хронология
- 2-4 достижения на место с цифрами
- разделы: Цель, Опыт, Навыки, Образование
- без таблиц и графики
- только текст""",

        "keywords": f"""Ты эксперт по ATS. Проанализируй резюме и ВЕРНИ ТОЛЬКО ДВЕ СТРОКИ:

Резюме:
{resume_text[:4000]}

Строка 1: 8-12 ключевых слов через запятую
Строка 2: 3 варианта заголовка резюме через точку с запятой""",

        "fixes": f"""Ты эксперт по ATS. Проанализируй резюме и напиши 6-10 точечных правок в формате:

Резюме:
{resume_text[:4000]}

Пункт 1: исправление
Пункт 2: исправление
...""",

        "recommendations": f"""Ты эксперт по ATS. Напиши 5-7 рекомендаций по загрузке резюме на hh.ru.

Резюме:
{resume_text[:4000]}

Рекомендации:
1. ...
2. ...""",

        "final_version": f"""Ты эксперт по ATS. Напиши финальную версию резюме в plain text, готовую для копирования.

Резюме:
{resume_text[:4000]}

Финальная версия (только текст):"""
    }

    payload = {
        "model": "deepseek-chat",
        "messages": [{"role": "user", "content": prompts[part_name]}],
        "temperature": 0.2,
        "max_tokens": 2000
    }

    response = requests.post(url, headers=headers, json=payload, timeout=120)
    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"].strip()

@app.route('/webhook', methods=['POST'])
def webhook():
    global stats, resume_cache
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
                f"📊 Статистика бота\n\n"
                f"Пользователей: {len(stats['users'])}\n"
                f"Запросов: {stats['total_requests']}")
            return 'ok', 200

        # /start с меню
        if text == '/start':
            keyboard = {
                "keyboard": [["📄 Загрузить резюме"], ["❓ Помощь"]],
                "resize_keyboard": True
            }
            send_message(chat_id,
                "📄 <b>ResumeEasy Bot</b>\n\n"
                "Я проведу полный ATS-анализ вашего резюме.\n\n"
                "Нажмите «Загрузить резюме» и отправьте PDF.",
                reply_markup=keyboard)
            return 'ok', 200

        if text == '❓ Помощь':
            send_message(chat_id,
                "📘 <b>Как работает бот</b>\n\n"
                "1. Загрузите PDF с резюме\n"
                "2. Бот проанализирует и выдаст кнопки\n"
                "3. Нажимайте кнопки — получайте результаты\n\n"
                "<b>Что вы получите:</b>\n"
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

        # Обработка нажатий на кнопки результатов
        if text.startswith('🔍'):
            resume_text = resume_cache.get(chat_id)
            if not resume_text:
                send_message(chat_id, "❌ Сессия истекла. Загрузите резюме заново.")
                return 'ok', 200

            if text == '🔍 Общий балл ATS':
                score = analyze_part(resume_text, "ats_score")
                try:
                    score_int = int(score)
                    emoji = get_score_emoji(score_int)
                    send_message(chat_id, f"{emoji} <b>Общий балл ATS: {score_int}/100</b>\n\n{emoji} Оценка: {score_int}/100")
                except:
                    send_message(chat_id, f"📊 <b>Общий балл ATS</b>\n\n{score}")

            elif text == '🔍 Детальный разбор по метрикам':
                metrics = analyze_part(resume_text, "detailed_metrics")
                parts = metrics.split(',')
                if len(parts) >= 6:
                    names = ["Ключевые слова", "Достижения (цифры)", "Форматирование", "Длина резюме", "Навыки (hard)", "Грамматика"]
                    msg = "<b>📊 Детальный разбор по метрикам</b>\n\n"
                    for i, name in enumerate(names):
                        try:
                            val = int(parts[i].strip())
                            emoji = get_score_emoji(val)
                            msg += f"{emoji} {name}: {val}/100\n"
                        except:
                            msg += f"• {name}: {parts[i].strip()}\n"
                    send_message(chat_id, msg)
                else:
                    send_message(chat_id, f"📊 <b>Метрики</b>\n\n{metrics}")

            elif text == '🔍 Готовая версия для hh.ru':
                result = analyze_part(resume_text, "hh_version")
                send_message(chat_id, f"📄 <b>Готовая версия для hh.ru</b>\n\n{result[:4000]}")

            elif text == '🔍 Ключевые слова и заголовки':
                result = analyze_part(resume_text, "keywords")
                send_message(chat_id, f"🔑 <b>Ключевые слова и заголовки</b>\n\n{result}")

            elif text == '🔍 Точечные правки':
                result = analyze_part(resume_text, "fixes")
                send_message(chat_id, f"✏️ <b>Точечные правки</b>\n\n{result}")

            elif text == '🔍 Рекомендации по загрузке':
                result = analyze_part(resume_text, "recommendations")
                send_message(chat_id, f"💡 <b>Рекомендации по загрузке на hh.ru</b>\n\n{result}")

            elif text == '🔍 Финальная версия резюме':
                result = analyze_part(resume_text, "final_version")
                send_message(chat_id, f"✅ <b>Финальная версия резюме</b>\n\n{result}")

            return 'ok', 200

        # Обработка PDF
        if 'document' in data['message']:
            doc = data['message']['document']
            if doc.get('mime_type') != 'application/pdf':
                send_message(chat_id, "❌ Отправьте PDF файл.")
                return 'ok', 200

            msg = send_message(chat_id, "🔍 Анализирую резюме... ⏳ 20-40 секунд")
            message_id = msg.json()['result']['message_id']

            # Скачиваем файл
            file_id = doc['file_id']
            file_info = requests.get(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getFile?file_id={file_id}").json()
            file_path = file_info['result']['file_path']
            file_url = f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{file_path}"
            file_content = requests.get(file_url, timeout=60).content

            # Извлекаем текст
            resume_text = extract_text_from_pdf(file_content)
            if not resume_text or len(resume_text.split()) < 50:
                edit_message(chat_id, message_id, "❌ Не удалось извлечь текст из PDF. Убедитесь, что файл не отсканирован.")
                return 'ok', 200

            # Сохраняем в кэш
            resume_cache[chat_id] = resume_text

            # Кнопки для навигации
            keyboard = {
                "keyboard": [
                    ["🔍 Общий балл ATS", "🔍 Детальный разбор по метрикам"],
                    ["🔍 Готовая версия для hh.ru", "🔍 Ключевые слова и заголовки"],
                    ["🔍 Точечные правки", "🔍 Рекомендации по загрузке"],
                    ["🔍 Финальная версия резюме"],
                    ["📄 Загрузить другое резюме", "❓ Помощь"]
                ],
                "resize_keyboard": True
            }

            edit_message(chat_id, message_id,
                "✅ <b>Резюме успешно загружено!</b>\n\n"
                "Выберите раздел для просмотра анализа:",
                reply_markup=keyboard)

            return 'ok', 200

        return 'ok', 200

    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return 'error', 500

@app.route('/', methods=['GET', 'HEAD'])
def index():
    return 'ResumeEasy Bot is running', 200

if __name__ != "__main__":
    logger.info("ResumeEasy Bot starting...")
