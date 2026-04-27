import os
import re
import json
import requests
from config import TELEGRAM_TOKEN, logger

def send_message(chat_id, text, reply_markup=None, parse_mode="HTML"):
    chunks = [text[i:i+4000] for i in range(0, len(text), 4000)]
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    for chunk in chunks:
        payload = {"chat_id": chat_id, "text": chunk, "parse_mode": parse_mode}
        if reply_markup and chunk == chunks[-1]:
            payload["reply_markup"] = json.dumps(reply_markup)
        try:
            requests.post(url, json=payload, timeout=30)
        except Exception as e:
            logger.error(f"Send error: {e}")

def send_welcome_video(chat_id, caption):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendVideo"
    video_path = "welcome.mp4"
    if not os.path.exists(video_path):
        logger.warning("Welcome video not found, sending text only.")
        send_message(chat_id, caption)
        return
    try:
        with open(video_path, "rb") as video:
            files = {"video": video}
            data = {"chat_id": chat_id, "caption": caption, "parse_mode": "HTML"}
            requests.post(url, files=files, data=data, timeout=60)
    except Exception as e:
        logger.error(f"Video send error: {e}")
        send_message(chat_id, caption)

def clean_markdown(text):
    text = re.sub(r'\*\*(.*?)\*\*', r'\1', text)
    text = re.sub(r'\*(.*?)\*', r'\1', text)
    text = re.sub(r'___(.*?)___', r'\1', text)
    text = re.sub(r'__(.*?)__', r'\1', text)
    text = re.sub(r'_(.*?)_', r'\1', text)
    return text

def extract_json(text):
    text = re.sub(r'```json\s*|\s*```', '', text).strip()
    try: 
        return json.loads(text)
    except:
        m = re.search(r'\{.*\}', text, re.DOTALL)
        if m:
            try: 
                return json.loads(m.group())
            except: 
                pass
    return None
