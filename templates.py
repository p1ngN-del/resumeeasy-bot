# templates.py — минимальные шаблоны для отчётов

REPORT_HTML = """
<!DOCTYPE html>
<html>
<head><title>Отчёт по резюме</title></head>
<body style="font-family: sans-serif; max-width: 800px; margin: 0 auto; padding: 20px; background: #0a0a1a; color: #fff;">
    <h1>📄 Отчёт по резюме</h1>
    <p><strong>Дата:</strong> {{ date }}</p>
    <p><strong>ATS-оценка:</strong> {{ ats }}/100</p>
    <p><strong>Общая оценка:</strong> {{ overall }}/100</p>
    <h2>Ключевые слова</h2>
    <ul>
    {% for kw in keywords %}
        <li>{{ kw }}</li>
    {% endfor %}
    </ul>
    <h2>Критические правки</h2>
    <ul>
    {% for fix in critical_fixes %}
        <li>{{ fix }}</li>
    {% endfor %}
    </ul>
    <h2>Вердикт</h2>
    <p>{{ verdict }}</p>
    <hr>
    <p style="color: #666; font-size: 12px;">Отчёт сгенерирован ботом ResumeEasy</p>
</body>
</html>
"""

MATCH_HTML = """
<!DOCTYPE html>
<html>
<head><title>Сравнение с вакансией</title></head>
<body style="font-family: sans-serif; max-width: 800px; margin: 0 auto; padding: 20px; background: #0a0a1a; color: #fff;">
    <h1>🎯 Сравнение с вакансией</h1>
    <p><strong>Совпадение:</strong> {{ match }}%</p>
    <h2>Отсутствующие навыки</h2>
    <ul>
    {% for skill in missing %}
        <li>{{ skill }}</li>
    {% endfor %}
    </ul>
    <h2>Рекомендации</h2>
    <ul>
    {% for rec in recs %}
        <li>{{ rec }}</li>
    {% endfor %}
    </ul>
    <p>{{ summary }}</p>
</body>
</html>
"""

COVER_HTML = """
<!DOCTYPE html>
<html>
<head><title>Сопроводительное письмо</title></head>
<body style="font-family: sans-serif; max-width: 800px; margin: 0 auto; padding: 20px; background: #0a0a1a; color: #fff;">
    <h1>📝 Сопроводительное письмо</h1>
    <pre style="white-space: pre-wrap; word-wrap: break-word; background: rgba(255,255,255,0.05); padding: 20px; border-radius: 12px;">{{ letter }}</pre>
</body>
</html>
"""

IMPROVED_HTML = """
<!DOCTYPE html>
<html>
<head><title>Улучшенное резюме</title></head>
<body style="font-family: sans-serif; max-width: 800px; margin: 0 auto; padding: 20px; background: #0a0a1a; color: #fff;">
    <h1>✨ Улучшенное резюме</h1>
    <p><strong>Дата:</strong> {{ date }}</p>
    <p><strong>ATS-оценка:</strong> {{ ats }}/100</p>
    <p><strong>Общая оценка:</strong> {{ overall }}/100</p>
    <h2>Блоки</h2>
    {% for block in blocks %}
        <h3>{{ block.title }}</h3>
        <pre style="white-space: pre-wrap; word-wrap: break-word; background: rgba(255,255,255,0.05); padding: 12px; border-radius: 8px;">{{ block.text }}</pre>
    {% endfor %}
    <p><strong>Итог:</strong> {{ summary }}</p>
</body>
</html>
"""

ADMIN_HTML = """
<!DOCTYPE html>
<html>
<head><title>Админ-панель</title></head>
<body style="font-family: sans-serif; max-width: 1200px; margin: 0 auto; padding: 20px; background: #0a0a1a; color: #fff;">
    <h1>📊 Админ-панель</h1>
    <p>Обновлено: {{ now }}</p>
    <div style="display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; margin: 20px 0;">
        <div style="background: rgba(255,255,255,0.05); padding: 16px; border-radius: 12px;">
            <h3>👥 Пользователей</h3>
            <p style="font-size: 32px;">{{ total_users }}</p>
        </div>
        <div style="background: rgba(255,255,255,0.05); padding: 16px; border-radius: 12px;">
            <h3>🆕 За сегодня</h3>
            <p style="font-size: 32px;">{{ new_today }}</p>
        </div>
        <div style="background: rgba(255,255,255,0.05); padding: 16px; border-radius: 12px;">
            <h3>📄 Анализов</h3>
            <p style="font-size: 32px;">{{ total_analyses }}</p>
        </div>
        <div style="background: rgba(255,255,255,0.05); padding: 16px; border-radius: 12px;">
            <h3>📈 Активных (7 дней)</h3>
            <p style="font-size: 32px;">{{ active_week }}</p>
        </div>
    </div>
    <h2>Последние пользователи</h2>
    <table style="width: 100%; border-collapse: collapse; text-align: left;">
        <tr style="border-bottom: 1px solid rgba(255,255,255,0.1);">
            <th style="padding: 8px;">ID</th>
            <th style="padding: 8px;">Username</th>
            <th style="padding: 8px;">Имя</th>
            <th style="padding: 8px;">Анализов</th>
            <th style="padding: 8px;">Средний ATS</th>
        </tr>
        {% for user in users %}
        <tr style="border-bottom: 1px solid rgba(255,255,255,0.05);">
            <td style="padding: 8px;">{{ user.user_id }}</td>
            <td style="padding: 8px;">{{ user.username or '-' }}</td>
            <td style="padding: 8px;">{{ user.first_name or '-' }}</td>
            <td style="padding: 8px;">{{ user.total }}</td>
            <td style="padding: 8px;">{{ user.avg_ats|round(1) }}</td>
        </tr>
        {% endfor %}
    </table>
</body>
</html>
"""

ADMIN_USERS_HTML = """
<!DOCTYPE html>
<html>
<head><title>Все пользователи</title></head>
<body style="font-family: sans-serif; max-width: 1200px; margin: 0 auto; padding: 20px; background: #0a0a1a; color: #fff;">
    <h1>👥 Все пользователи</h1>
    <p><a href="/admin" style="color: #64ffda;">← Назад</a></p>
    <table style="width: 100%; border-collapse: collapse; text-align: left;">
        <tr style="border-bottom: 1px solid rgba(255,255,255,0.1);">
            <th style="padding: 8px;">ID</th>
            <th style="padding: 8px;">Username</th>
            <th style="padding: 8px;">Имя</th>
            <th style="padding: 8px;">Дата регистрации</th>
            <th style="padding: 8px;">Анализов</th>
            <th style="padding: 8px;">Средний ATS</th>
        </tr>
        {% for user in users %}
        <tr style="border-bottom: 1px solid rgba(255,255,255,0.05);">
            <td style="padding: 8px;">{{ user.user_id }}</td>
            <td style="padding: 8px;">{{ user.username or '-' }}</td>
            <td style="padding: 8px;">{{ user.first_name or '-' }}</td>
            <td style="padding: 8px;">{{ user.join_date.strftime('%d.%m.%Y') if user.join_date else '-' }}</td>
            <td style="padding: 8px;">{{ user.total }}</td>
            <td style="padding: 8px;">{{ user.avg_ats|round(1) }}</td>
        </tr>
        {% endfor %}
    </table>
</body>
</html>
"""
