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

def analyze_resume(resume_text):
    url = "https://api.deepseek.com/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json"
    }

    prompt = f"""Ты — старший HR-рекрутер и эксперт по ATS с 10+ лет опыта в России, знакомый с текущими алгоритмами парсинга и требованиями hh.ru (2026). Твоя задача — проанализировать предоставленное резюме кандидата и дать развернутую, максимально полезную обратную связь, чтобы сделать резюме идеальным для отклика на вакансии в России и прохода через ATS hh.ru.

Выполни следующие шаги строго по порядку. НЕ ИСПОЛЬЗУЙ ЗВЁЗДОЧКИ. Используй HTML-теги <b>текст</b> для жирного.

Резюме:
{resume_text[:6000]}

1. АНАЛИЗ ИСХОДНОГО РЕЗЮМЕ
Укажи сильные и слабые стороны по структуре, контенту, ключевым словам и читабельности для рекрутера и парсера.

2. ATS-ОЦЕНКА (от 0 до 100)
Выстави объективную оценку. Учитывай: отсутствие таблиц, колонок, сложной верстки, графики, иконок. Наличие ключевых слов. Чистый plain text. Стандартные названия разделов. Отсутствие фото.
Сними баллы: фото -5, колонтитулы -3, графика/иконки -3, таблицы -5, нестандартные заголовки -2, слишком длинное -3. Дай рекомендации.

3. ОБЩАЯ ОЦЕНКА РЕЗЮМЕ (от 0 до 100)
Оцени контент и подачу. Учитывай: четкость цели, измеримые достижения с метриками, action-verbs, обратная хронология, группировка навыков, наличие разделов, объем страниц, отсутствие общих фраз.
Сними баллы: нет метрик -5 за буллет, общие фразы -3, нет цели -3, нет группировки навыков -2, превышение объема -3.

4. ТРИ ВАРИАНТА ЗАГОЛОВКА РЕЗЮМЕ (для поля «Желаемая должность» на hh.ru)

5. БЛОК ATS-READY: 8-12 РЕЛЕВАНТНЫХ КЛЮЧЕВЫХ СЛОВ/ФРАЗ

6. ТОЧЕЧНЫЕ ПРАВКИ ФОРМУЛИРОВОК (минимум 6-10 мест)
Формат: Исходный пункт → Исправленный пункт

7. РЕКОМЕНДАЦИИ ПО ФОРМАТИРОВАНИЮ И ЗАГРУЗКЕ НА hh.ru
Какие поля заполнить, как вставить ссылки, какие фильтры выбрать, как оформить навыки. Предупреждение: никакого жирного шрифта, таблиц, иконок — только plain text.

8. ОЦЕНКА СООТВЕТСТВИЯ (MATCH SCORE) ДО 100%
Предложи 3 типа вакансий для поиска. Укажи, какие фразы/навыки добавить или убрать.

9. ТРИ ВЕРСИИ РЕЗЮМЕ
Версия А (plain text для hh.ru, не более 2 стр.)
Версия Б (сопроводительное письмо: summary 3-5 строк + 3 буллета достижений)
Версия В (для Word/PDF — структурные заголовки, группировка навыков, без таблиц)

10. ФИНАЛЬНЫЙ ВЕРДИКТ
Краткое резюме: готово ли к рассылке, топ-3 критических исправлений, прогноз конверсии «Просмотр → Приглашение»."""

    payload = {
        "model": "deepseek-chat",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0,
        "max_tokens": 4500
    }

    response = requests.post(url, headers=headers, json=payload, timeout=180)
    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"]

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
        "Я проведу полный ATS-анализ вашего резюме.\n\n"
        "Нажмите «Загрузить резюме» и отправьте PDF.",
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

        if text == '/admin':
            send_message(chat_id, f"📊 Статистика\nПользователей: {len(stats['users'])}\nЗапросов: {stats['total_requests']}")
            return 'ok', 200

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
                "• ATS-оценку (0-100)\n"
                "• Общую оценку резюме (0-100)\n"
                "• Детальный разбор с рекомендациями\n"
                "• Три варианта заголовка\n"
                "• Ключевые слова (8-12)\n"
                "• Точечные правки (6-10)\n"
                "• Три версии резюме\n\n"
                "🔄 Для нового резюме нажмите «Загрузить другое резюме»")
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

        # Обработка кнопки "Полный анализ"
        if text == '🔍 Полный ATS-анализ':
            resume_text = resume_cache.get(chat_id)
            if not resume_text:
                show_main_menu(chat_id)
                send_message(chat_id, "❌ Сессия истекла. Загрузите резюме заново.")
                return 'ok', 200

            send_message(chat_id, "🔍 <b>Выполняю полный анализ...</b>\n⏳ 30-60 секунд")
            
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
                send_message(chat_id, "❌ Не удалось извлечь текст из PDF. Убедитесь, что файл не отсканирован.")
                return 'ok', 200

            resume_cache[chat_id] = resume_text

            keyboard = {
                "keyboard": [
                    ["🔍 Полный ATS-анализ"],
                    ["📄 Загрузить другое резюме", "🔙 Главное меню"]
                ],
                "resize_keyboard": True
            }

            send_message(chat_id, "✅ <b>Резюме загружено!</b>\n\nНажмите «Полный ATS-анализ» для детального разбора по 10 пунктам.", reply_markup=keyboard)
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
