#!/usr/bin/env python3
import os
import io
import logging
import requests
from flask import Flask, request
from PyPDF2 import PdfReader

# === Конфигурация ===
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY")

if not TELEGRAM_TOKEN or not DEEPSEEK_API_KEY:
    raise ValueError("Missing TELEGRAM_TOKEN or DEEPSEEK_API_KEY")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

def send_message(chat_id, text):
    """Отправка сообщения в Telegram"""
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        requests.post(url, json={"chat_id": chat_id, "text": text}, timeout=30)
    except Exception as e:
        logger.error(f"Send error: {e}")

def extract_text_from_pdf(file_bytes):
    """Извлечение текста из PDF"""
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
    """Отправка текста в DeepSeek и получение анализа"""
    url = "https://api.deepseek.com/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json"
    }
    
    prompt = f"""Ты — старший HR-рекрутер и эксперт по ATS с 10+ лет опыта в России, знаком с текущими алгоритмами парсинга и требованиями hh.ru (2026). Твоя задача — взять предоставленное резюме кандидата и сделать его идеальным для отклика на вакансии в России и прохода через ATS hh.ru.

Выполни следующее:

1) Проанализируй исходное резюме (ниже) и укажи сильные/слабые стороны по структуре, контенту, ключевым словам и читабельности для рекрутера и парсера.
2) Преобразуй резюме в две готовые версии:
   A. Версия для загрузки в профиль hh.ru и Word/PDF (чёткая, не более 1 страницы при опыте <10 лет, максимум 2 страницы для senior): аккуратные заголовки, обратная хронология, 2–4 достижения на каждое место с метриками, разделы: Цель/Позиция, Опыт работы, Ключевые достижения, Навыки (группировка: Технологии/Инструменты/Языки/Soft), Образование, Сертификаты, Портфолио/ссылки, Дополнительно. Убери графику/таблицы и сложное форматирование, оставь plain text, готовый для копирования.
   B. Версия для отправки через сопроводительное сообщение (короткая адаптация/summary 3–5 строк + ключевые достижения 3 буллета).
3) Сгенерируй блок «ATS-ready»: 8–12 релевантных ключевых слов/фраз и 3 варианта заголовка резюме (для hh.ru), включая наиболее вероятные синонимы вакансий.
4) Дай точечные правки/подстановки: улучшенные формулировки 6–10 ключевых буллетов достижений (конкретные, с метриками), замену общих фраз на результат-ориентированные, и варианты ACTION-VERB начала (в русском: «Увеличил/Сократил/Оптимизировал/Внедрил...»).
5) Укажи рекомендации по форматированию и загрузке на hh.ru: оптимальные поля (заголовок, зарплата, релокация), рекомендуемые фильтры и категории, советы по заполнению портфолио/проекта, и как корректно вставить ссылки.
6) Оценка соответствия (match score) до 100% против целевой вакансии: предложи как минимум 3 вакансии/ключевых фреймворка (слова для поиска) на hh.ru, под которые лучше оптимизировать резюме, и какие фразы/навыки добавить/убрать для повышения score.
7) Выполни все правки в формате «Исходный пункт → Исправленный пункт» для минимум 10 мест (заголовков/буллетов/описаний), и выведи финальную готовую версию резюме в plain text.

Платформа - hh.ru

Вот резюме кандидата:
---
{resume_text[:8000]}
---

Ответь ДЕТАЛЬНО, соблюдая все пункты выше. Начинай каждый пункт с новой строки. Используй эмодзи для визуального выделения."""

    payload = {
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": "Ты — эксперт по ATS и HR с опытом в России."},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.3,
        "max_tokens": 4000
    }

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=120)
        response.raise_for_status()
        result = response.json()
        return result["choices"][0]["message"]["content"]
    except Exception as e:
        logger.error(f"DeepSeek error: {e}")
        return f"❌ Ошибка при анализе: {str(e)}"

@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        data = request.get_json()
        if 'message' not in data:
            return 'ok', 200

        chat_id = data['message']['chat']['id']
        
        # Обработка команды /start
        if 'text' in data['message'] and data['message']['text'] == '/start':
            send_message(chat_id, "📄 *ResumeEasy Bot*\n\nОтправьте мне PDF-файл с резюме, и я проведу полный ATS-анализ по стандартам hh.ru 2026.")
            return 'ok', 200

        # Обработка PDF
        if 'document' in data['message']:
            doc = data['message']['document']
            if doc.get('mime_type') != 'application/pdf':
                send_message(chat_id, "❌ Пожалуйста, отправьте файл в формате PDF.")
                return 'ok', 200

            send_message(chat_id, "🔍 Получил PDF. Анализирую...\n* Это может занять 20-40 секунд.")

            # Скачиваем файл
            file_id = doc['file_id']
            file_info = requests.get(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getFile?file_id={file_id}").json()
            file_path = file_info['result']['file_path']
            file_url = f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{file_path}"
            file_content = requests.get(file_url).content

            # Извлекаем текст
            resume_text = extract_text_from_pdf(file_content)
            if not resume_text or len(resume_text.split()) < 50:
                send_message(chat_id, "❌ Не удалось извлечь текст из PDF. Убедитесь, что файл не отсканирован и содержит текст.")
                return 'ok', 200

            # Анализируем через DeepSeek
            analysis = analyze_with_deepseek(resume_text)
            
            # Отправляем результат (с разбивкой на части, если длинный)
            if len(analysis) > 4096:
                for i in range(0, len(analysis), 4096):
                    send_message(chat_id, analysis[i:i+4096])
            else:
                send_message(chat_id, analysis)
            
            return 'ok', 200

        send_message(chat_id, "Отправьте PDF-файл с резюме для ATS-анализа.")
        return 'ok', 200

    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return 'error', 500

@app.route('/', methods=['GET', 'HEAD'])
def index():
    return 'ResumeEasy Bot is running', 200

if __name__ != "__main__":
    logger.info("ResumeEasy Bot starting...")
