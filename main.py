#!/usr/bin/env python3
from flask import Flask
from config import logger
from database import init_db
from handlers import register_routes

app = Flask(__name__)

# Регистрируем все маршруты из handlers.py
register_routes(app)

# Инициализация БД
init_db()
logger.info("🚀 Started")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
