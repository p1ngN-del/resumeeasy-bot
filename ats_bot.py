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
stats = {"users": set(), "total_requests": 0}
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
        "ats_score": f"Оцени общий балл ATS резюме от 0 до 100. Ответь ТОЛЬКО числом. БЕЗ ТЕКСТА. БЕЗ ЗВЁЗДОЧЕК.\n\nРезюме:\n{resume_text[:4000]}",
        "overall_score": f"Оцени общее качество резюме от 0 до 100. Ответь ТОЛЬКО числом. БЕЗ ТЕКСТА. БЕЗ ЗВЁЗДОЧЕК.\n\nРезюме:\n{resume_text[:4000]}",
        "metrics_with_fixes": f"""Оцени 6 метрик резюме от 0 до 100. Для каждой метрики напиши оценку и конкретную рекомендацию по улучшению.

Метрики:
1. Ключевые слова
2. Достижения с цифрами
3. Форматирование
4. Длина резюме
5. Навыки (hard skills)
6. Грамматика и стиль

ФОРМАТ ОТВЕТА (строго):
Метрика: X/100
Рекомендация: текст...

Резюме:
{resume_text[:4000]}""",
        "final_version": f"Напиши финальную версию резюме в plain text. БЕЗ ЗВЁЗДОЧЕК. БЕЗ HTML.\n\nРезюме:\n{resume_text[:4000]}"
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

def show_main_menu(chat_id):
    keyboard = {
        "keyboard": [
            ["📄 Загрузить резюме"],
            ["❓ Помощь", "📊 Статистика"]
        ],
        "resize_keyboard": True
    }
    send_message(chat_id,
        "📄 <b>ResumeEasy Bot</b>\n\n"
        "Я проведу ATS-анализ вашего резюме.\n\n"
        "▸ Нажмите «Загрузить резюме» и отправьте PDF\n"
        "▸ Получите общий балл, разбор по 6 метрикам с рекомендациями\n"
        "▸ И финальную версию резюме",
        reply_markup=keyboard)

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

        # Админ-команда (скрытая)
        if text == '/admin':
            send_message(chat_id, f"📊 Статистика\nПользователей: {len(stats['users'])}\nЗапросов: {stats['total_requests']}")
            return 'ok', 200

        # Обработка команд
        if text == '/start':
            show_main_menu(chat_id)
            return 'ok', 200

        if text == '❓ Помощь':
            send_message(chat_id, 
                "📘 <b>Как пользоваться ботом</b>\n\n"
                "1️⃣ Нажмите «Загрузить резюме»\n"
                "2️⃣ Отправьте PDF-файл\n"
                "3️⃣ Дождитесь анализа (20-40 секунд)\n\n"
                "📊 <b>Что вы получите:</b>\n"
                "• Общий балл ATS (0-100)\n"
                "• Общую оценку резюме (0-100)\n"
                "• Детальный разбор по 6 метрикам с рекомендациями\n"
                "• Финальную версию резюме\n\n"
                "🔄 Для нового резюме нажмите «Загрузить другое резюме»\n"
                "🔙 Для возврата в главное меню нажмите «Главное меню»")
            return 'ok', 200

        if text == '📊 Статистика':
            send_message(chat_id, 
                f"📊 <b>Ваша статистика</b>\n\n"
                f"📄 Всего анализов: {stats['total_requests']}\n"
                f"👤 ID: <code>{chat_id}</code>")
            return 'ok', 200

        if text == '🔙 Главное меню':
            show_main_menu(chat_id)
            return 'ok', 200

        if text == '📄 Загрузить резюме' or text == '📄 Загрузить другое резюме':
            send_message(chat_id, "📎 Отправьте PDF-файл с резюме.")
            return 'ok', 200

        # Обработка кнопок после загрузки резюме
        if text in ['📊 Общий балл ATS', '📈 Общая оценка резюме', '🔍 Детальный разбор с рекомендациями', '✅ Финальная версия резюме']:
            resume_text = resume_cache.get(chat_id)
            if not resume_text:
                show_main_menu(chat_id)
                send_message(chat_id, "❌ Сессия истекла. Загрузите резюме заново.")
                return 'ok', 200

            if text == '📊 Общий балл ATS':
                score = analyze_part(resume_text, "ats_score")
                try:
                    score_int = int(score)
                    send_message(chat_id, f"{get_score_emoji(score_int)} <b>Общий балл ATS: {score_int}/100</b>")
                except:
                    send_message(chat_id, f"📊 Общий балл ATS: {score}")

            elif text == '📈 Общая оценка резюме':
                score = analyze_part(resume_text, "overall_score")
                try:
                    score_int = int(score)
                    send_message(chat_id, f"{get_score_emoji(score_int)} <b>Общая оценка резюме: {score_int}/100</b>")
                except:
                    send_message(chat_id, f"📈 Общая оценка: {score}")

            elif text == '🔍 Детальный разбор с рекомендациями':
                result = analyze_part(resume_text, "metrics_with_fixes")
                send_message(chat_id, f"🔍 <b>Детальный разбор по метрикам</b>\n\n{result}")

            elif text == '✅ Финальная версия резюме':
                result = analyze_part(resume_text, "final_version")
                send_message(chat_id, f"✅ <b>Финальная версия резюме</b>\n\n{result}")

            return 'ok', 200

        # Обработка PDF
        if 'document' in data['message']:
            doc = data['message']['document']
            if doc.get('mime_type') != 'application/pdf':
                send_message(chat_id, "❌ Отправьте PDF файл.")
                return 'ok', 200

            send_message(chat_id, "🔍 <b>Анализирую резюме...</b>\n⏳ 20-40 секунд")

            file_id = doc['file_id']
            file_info = requests.get(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getFile?file_id={file_id}").json()
            file_path = file_info['result']['file_path']
            file_url = f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{file_path}"
            file_content = requests.get(file_url, timeout=60).content

            resume_text = extract_text_from_pdf(file_content)
            if not resume_text or len(resume_text.split()) < 50:
                send_message(chat_id, "❌ Не удалось извлечь текст из PDF.")
                return 'ok', 200

            resume_cache[chat_id] = resume_text

            keyboard = {
                "keyboard": [
                    ["📊 Общий балл ATS", "📈 Общая оценка резюме"],
                    ["🔍 Детальный разбор с рекомендациями"],
                    ["✅ Финальная версия резюме"],
                    ["📄 Загрузить другое резюме", "🔙 Главное меню"]
                ],
                "resize_keyboard": True
            }

            send_message(chat_id, "✅ <b>Резюме загружено!</b>\n\nВыберите, что хотите получить:", reply_markup=keyboard)
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
