#!/usr/bin/env python3
import os
import io
import logging
import requests
import sys
from flask import Flask, request
from PyPDF2 import PdfReader

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY")

if not TELEGRAM_TOKEN or not DEEPSEEK_API_KEY:
    raise ValueError("Missing TELEGRAM_TOKEN or DEEPSEEK_API_KEY")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

def send_message(chat_id, text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        requests.post(url, json={"chat_id": chat_id, "text": text}, timeout=30)
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
    
    prompt = f"""Ты — старший HR-рекрутер и эксперт по ATS с 10+ лет опыта в России. Проанализируй резюме и выполни все пункты.

Резюме:
{resume_text[:8000]}

Выдай:
1) Анализ сильных/слабых сторон
2) Готовую версию для hh.ru
3) Ключевые слова (8-12)
4) Точечные правки (6-10)
5) Рекомендации по загрузке на hh.ru
6) Match score (0-100%) и целевые вакансии
7) Финальную версию"""

    payload = {
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": "Ты — эксперт по ATS и HR."},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.3,
        "max_tokens": 4000
    }

    # Увеличиваем таймаут до 180 секунд
    response = requests.post(url, headers=headers, json=payload, timeout=180)
    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"]

@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        data = request.get_json()
        if 'message' not in data:
            return 'ok', 200

        chat_id = data['message']['chat']['id']
        
        if 'text' in data['message'] and data['message']['text'] == '/start':
            send_message(chat_id, "📄 *ResumeEasy Bot*\n\nОтправьте PDF с резюме.")
            return 'ok', 200

        if 'document' in data['message']:
            doc = data['message']['document']
            if doc.get('mime_type') != 'application/pdf':
                send_message(chat_id, "❌ Отправьте PDF файл.")
                return 'ok', 200

            send_message(chat_id, "🔍 Анализирую PDF... (20-40 секунд)")

            try:
                # Скачиваем файл
                file_id = doc['file_id']
                file_info = requests.get(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getFile?file_id={file_id}").json()
                file_path = file_info['result']['file_path']
                file_url = f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{file_path}"
                file_content = requests.get(file_url, timeout=60).content

                # Извлекаем текст
                resume_text = extract_text_from_pdf(file_content)
                if not resume_text or len(resume_text.split()) < 50:
                    send_message(chat_id, "❌ Не удалось извлечь текст из PDF.")
                    return 'ok', 200

                # Анализируем
                analysis = analyze_with_deepseek(resume_text)
                
                # Отправляем результат
                if len(analysis) > 4096:
                    for i in range(0, len(analysis), 4096):
                        send_message(chat_id, analysis[i:i+4096])
                else:
                    send_message(chat_id, analysis)

            except requests.exceptions.Timeout:
                send_message(chat_id, "❌ DeepSeek не ответил вовремя. Попробуйте ещё раз.")
            except Exception as e:
                logger.error(f"Processing error: {e}")
                send_message(chat_id, f"❌ Ошибка: {str(e)[:200]}")
            
            return 'ok', 200

        send_message(chat_id, "Отправьте PDF файл.")
        return 'ok', 200

    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return 'error', 500

@app.route('/', methods=['GET', 'HEAD'])
def index():
    return 'ResumeEasy Bot is running', 200

if __name__ != "__main__":
    logger.info("ResumeEasy Bot starting...")
