#!/usr/bin/env python3
import os
import io
import logging
import requests
from flask import Flask, request
from PyPDF2 import PdfReader

# === Конфигурация из переменных окружения ===
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

# === ВРЕМЕННАЯ ЗАГЛУШКА (потом заменим на DeepSeek) ===
def analyze_with_deepseek(resume_text):
    # Пока просто возвращаем извлечённый текст
    return f"✅ Резюме получено! Текст успешно извлечён.\n\nПервые 500 символов:\n{resume_text[:500]}"

@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        data = request.get_json()
        if 'message' not in data:
            return 'ok', 200

        chat_id = data['message']['chat']['id']
        
        # Обработка команды /start
        if 'text' in data['message'] and data['message']['text'] == '/start':
            send_message(chat_id, "📄 *ResumeEasy Bot*\n\nОтправьте мне PDF-файл с резюме, и я проанализирую его.", parse_mode="Markdown")
            return 'ok', 200

        # Обработка PDF
        if 'document' in data['message']:
            doc = data['message']['document']
            if doc.get('mime_type') != 'application/pdf':
                send_message(chat_id, "❌ Пожалуйста, отправьте файл в формате PDF.")
                return 'ok', 200

            send_message(chat_id, "🔍 Получил PDF. Анализирую... (20-40 секунд)")

            # 1. Скачиваем файл
            file_id = doc['file_id']
            file_info = requests.get(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getFile?file_id={file_id}").json()
            file_path = file_info['result']['file_path']
            file_url = f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{file_path}"
            file_content = requests.get(file_url).content

            # 2. Извлекаем текст
            resume_text = extract_text_from_pdf(file_content)
            if not resume_text or len(resume_text.split()) < 20:
                send_message(chat_id, "❌ Не удалось извлечь текст из PDF. Убедитесь, что файл не отсканирован.")
                return 'ok', 200

            # 3. Анализ (пока заглушка)
            analysis = analyze_with_deepseek(resume_text)
            
            # 4. Отправляем результат
            if len(analysis) > 4096:
                for i in range(0, len(analysis), 4096):
                    send_message(chat_id, analysis[i:i+4096])
            else:
                send_message(chat_id, analysis)
            
            return 'ok', 200

        send_message(chat_id, "Отправьте PDF-файл с резюме.")
        return 'ok', 200

    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return 'error', 500

@app.route('/', methods=['GET', 'HEAD'])
def index():
    return 'ResumeEasy Bot is running', 200

if __name__ != "__main__":
    logger.info("ResumeEasy Bot starting...")
