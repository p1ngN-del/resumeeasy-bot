#!/usr/bin/env python3
from flask import Flask
from config import logger
from database import init_db
from handlers import register_routes
from web import web_bp

app = Flask(__name__)

# Telegram бот и отчёты
register_routes(app)

# Веб-сайт (лендинг + загрузка)
app.register_blueprint(web_bp)

init_db()
logger.info("🚀 Started")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
