REPORT_HTML = """
<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Resume Expert Report</title>
    <style>
        body { background-color: #121212; color: #e0e0e0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; margin: 0; padding: 20px; line-height: 1.6; }
        .container { max-width: 800px; margin: 0 auto; background: #1e1e1e; padding: 30px; border-radius: 12px; box-shadow: 0 4px 20px rgba(0,0,0,0.5); }
        h1 { color: #ffffff; border-bottom: 2px solid #333; padding-bottom: 15px; margin-top: 0; font-size: 24px; }
        h2 { color: #bb86fc; margin-top: 30px; font-size: 18px; border-left: 4px solid #bb86fc; padding-left: 10px; }
        .score-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 15px; margin-bottom: 20px; }
        .score-card { background: #2c2c2c; padding: 15px; border-radius: 8px; text-align: center; }
        .score-val { font-size: 32px; font-weight: bold; color: #03dac6; }
        .score-label { font-size: 14px; color: #aaa; margin-top: 5px; }
        .tag { display: inline-block; background: #333; padding: 4px 8px; border-radius: 4px; margin: 2px; font-size: 12px; color: #03dac6; }
        .checklist-item { display: flex; align-items: flex-start; padding: 12px; margin-bottom: 10px; background: #252525; border-radius: 8px; border-left: 4px solid #555; }
        .checklist-item.critical { border-left-color: #cf6679; }
        .checklist-item.metrics { border-left-color: #ffb74d; }
        .checklist-item.style { border-left-color: #03dac6; }
        .checklist-checkbox { margin-right: 12px; margin-top: 3px; width: 20px; height: 20px; cursor: pointer; }
        .checklist-content { flex: 1; }
        .checklist-title { font-weight: bold; margin-bottom: 4px; }
        .checklist-desc { font-size: 13px; color: #aaa; }
        .verdict-box { background: #1a1a2e; border: 1px solid #bb86fc; padding: 15px; border-radius: 8px; margin-top: 20px; }
        .verbatim { white-space: pre-wrap; background: #252525; padding: 15px; border-radius: 6px; font-size: 14px; }
        .footer { margin-top: 40px; text-align: center; font-size: 12px; color: #666; }
        .category-header { display: flex; align-items: center; gap: 10px; margin-top: 20px; }
        .category-badge { padding: 4px 10px; border-radius: 12px; font-size: 12px; font-weight: bold; }
        .badge-critical { background: #cf6679; color: #000; }
        .badge-metrics { background: #ffb74d; color: #000; }
        .badge-style { background: #03dac6; color: #000; }
        .btn-generate { display: block; width: 100%; padding: 15px; background: #bb86fc; color: #000; text-align: center; text-decoration: none; font-weight: bold; border-radius: 8px; margin-top: 20px; cursor: pointer; border: none; font-size: 16px; }
        .btn-generate:disabled { opacity: 0.5; cursor: not-allowed; }
        .btn-copy { display: block; width: 100%; padding: 15px; background: #03dac6; color: #000; text-align: center; text-decoration: none; font-weight: bold; border-radius: 8px; margin-top: 10px; cursor: pointer; border: none; font-size: 16px; }
        #improvedResume { margin-top: 30px; padding: 20px; background: #1a1a2e; border-radius: 10px; border: 2px solid #bb86fc; }
    </style>
</head>
<body>
    <div class="container">
        <h1>📊 Expert Resume Analysis</h1>
        <p style="color: #888">Generated on {{ date }}</p>

        <div class="score-grid">
            <div class="score-card">
                <div class="score-val">{{ overall }}/100</div>
                <div class="score-label">Общая оценка HR</div>
            </div>
            <div class="score-card">
                <div class="score-val" style="color: #bb86fc">{{ ats }}/100</div>
                <div class="score-label">ATS Score (hh.ru)</div>
            </div>
        </div>

        <h2>✅ Чек-лист улучшений</h2>
        <p style="color:#888; font-size:13px">Отметьте правки, которые хотите применить → нажмите «Сгенерировать»</p>

        <div class="category-header">
            <span class="category-badge badge-critical">🔴 КРИТИЧНО</span>
            <span style="color:#aaa; font-size:13px">Мешают ATS найти резюме</span>
        </div>
        {% for fix in critical_fixes %}
        <div class="checklist-item critical">
            <input type="checkbox" class="checklist-checkbox">
            <div class="checklist-content">
                <div class="checklist-title">{{ fix.title }}</div>
                <div class="checklist-desc">{{ fix.description }}</div>
            </div>
        </div>
        {% endfor %}

        <div class="category-header">
            <span class="category-badge badge-metrics">🟡 МЕТРИКИ</span>
            <span style="color:#aaa; font-size:13px">Добавьте цифры и результаты</span>
        </div>
        {% for fix in metrics_fixes %}
        <div class="checklist-item metrics">
            <input type="checkbox" class="checklist-checkbox">
            <div class="checklist-content">
                <div class="checklist-title">{{ fix.title }}</div>
                <div class="checklist-desc">{{ fix.description }}</div>
            </div>
        </div>
        {% endfor %}

        <div class="category-header">
            <span class="category-badge badge-style">🟢 СТИЛЬ</span>
            <span style="color:#aaa; font-size:13px">Язык, глаголы, подача</span>
        </div>
        {% for fix in style_fixes %}
        <div class="checklist-item style">
            <input type="checkbox" class="checklist-checkbox">
            <div class="checklist-content">
                <div class="checklist-title">{{ fix.title }}</div>
                <div class="checklist-desc">{{ fix.description }}</div>
            </div>
        </div>
        {% endfor %}

        <button class="btn-generate" onclick="generateResume()" id="genBtn">
            ✨ Сгенерировать улучшенное резюме
        </button>

        <div id="improvedResume" style="display:none;">
            <h2 style="color:#03dac6; margin-top:0;">✨ Улучшенное резюме</h2>
            <div class="verbatim" id="improvedText"></div>
            <button class="btn-copy" onclick="copyImproved()">📋 Скопировать текст</button>
        </div>

        <h2>🎯 Варианты заголовка для hh.ru</h2>
        <div class="verbatim">
        {% for h in headlines %}• {{ h }}<br>{% endfor %}
        </div>

        <h2>🔑 Ключевые слова для ATS</h2>
        <div>
        {% for k in keywords %}<span class="tag">{{ k }}</span>{% endfor %}
        </div>

        <h2>💡 Рекомендации по hh.ru</h2>
        <div class="verbatim">{{ hh_rec }}</div>

        <h2>📈 Подходящие вакансии</h2>
        <div class="verbatim">
        {% for v in match_vac %}• {{ v }}<br>{% endfor %}
        </div>

        <div class="verdict-box">
            <h2>🎤 Финальный вердикт</h2>
            <div class="verbatim">{{ verdict }}</div>
        </div>

        <div class="footer">Powered by ResumeEasy Bot</div>
    </div>

    <input type="hidden" id="reportId" value="{{ report_id }}">

    <script>
        function generateResume() {
            const selected = [];
            document.querySelectorAll('.checklist-checkbox:checked').forEach(cb => {
                const item = cb.closest('.checklist-item');
                selected.push({
                    title: item.querySelector('.checklist-title').innerText,
                    desc: item.querySelector('.checklist-desc').innerText
                });
            });
            
            if (selected.length === 0) {
                alert('Выберите хотя бы одну правку!');
                return;
            }
            
            document.getElementById('genBtn').innerText = '⏳ Генерирую...';
            document.getElementById('genBtn').disabled = true;
            
            fetch('/api/improve', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({report_id: document.getElementById('reportId').value, fixes: selected})
            })
            .then(r => r.json())
            .then(data => {
                document.getElementById('improvedText').innerText = data.text;
                document.getElementById('improvedResume').style.display = 'block';
                document.getElementById('genBtn').innerText = '✅ Готово!';
                document.getElementById('genBtn').disabled = false;
            })
            .catch(() => {
                document.getElementById('genBtn').innerText = '❌ Ошибка';
                document.getElementById('genBtn').disabled = false;
            });
        }

        function copyImproved() {
            navigator.clipboard.writeText(document.getElementById('improvedText').innerText)
                .then(() => alert('Скопировано!'));
        }
    </script>
</body>
</html>
"""

MATCH_HTML = """
<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Job Match Report</title>
    <style>
        body { background-color: #121212; color: #e0e0e0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; margin: 0; padding: 20px; line-height: 1.6; }
        .container { max-width: 800px; margin: 0 auto; background: #1e1e1e; padding: 30px; border-radius: 12px; box-shadow: 0 4px 20px rgba(0,0,0,0.5); }
        h1 { color: #ffffff; border-bottom: 2px solid #333; padding-bottom: 15px; margin-top: 0; font-size: 24px; }
        h2 { color: #bb86fc; margin-top: 30px; font-size: 18px; border-left: 4px solid #bb86fc; padding-left: 10px; }
        .score-card { background: #2c2c2c; padding: 20px; border-radius: 8px; text-align: center; margin-bottom: 20px; }
        .score-val { font-size: 48px; font-weight: bold; color: #03dac6; }
        .score-label { font-size: 16px; color: #aaa; margin-top: 5px; }
        .list-item { background: #252525; padding: 10px; margin-bottom: 8px; border-radius: 6px; border-left: 3px solid #cf6679; }
        .rec-item { background: #252525; padding: 10px; margin-bottom: 8px; border-radius: 6px; border-left: 3px solid #03dac6; }
        .summary { background: #333; padding: 15px; border-radius: 6px; margin-bottom: 20px; font-style: italic; }
        .footer { margin-top: 40px; text-align: center; font-size: 12px; color: #666; }
    </style>
</head>
<body>
    <div class="container">
        <h1>🎯 Job Match Analysis</h1>
        <p style="color: #888">Generated on {{ date }}</p>
        <div class="score-card">
            <div class="score-val">{{ match }}/100</div>
            <div class="score-label">Совпадение с вакансией</div>
        </div>
        <div class="summary">{{ summary }}</div>
        <h2>❌ Недостающие навыки</h2>
        {% for skill in missing %}<div class="list-item">• {{ skill }}</div>{% endfor %}
        <h2>💡 Рекомендации по улучшению</h2>
        {% for rec in recs %}<div class="rec-item">• {{ rec }}</div>{% endfor %}
        <div class="footer">Powered by ResumeEasy Bot</div>
    </div>
</body>
</html>
"""

COVER_HTML = """
<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Cover Letter</title>
    <style>
        body { background-color: #121212; color: #e0e0e0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; margin: 0; padding: 20px; line-height: 1.6; }
        .container { max-width: 800px; margin: 0 auto; background: #1e1e1e; padding: 40px; border-radius: 12px; box-shadow: 0 4px 20px rgba(0,0,0,0.5); }
        h1 { color: #ffffff; border-bottom: 2px solid #333; padding-bottom: 15px; margin-top: 0; font-size: 24px; }
        .letter-content { white-space: pre-wrap; background: #252525; padding: 20px; border-radius: 8px; font-size: 16px; line-height: 1.8; border: 1px solid #333; }
        .btn-copy { display: block; width: 100%; padding: 15px; background: #03dac6; color: #000; text-align: center; text-decoration: none; font-weight: bold; border-radius: 8px; margin-top: 20px; cursor: pointer; border: none; font-size: 16px; }
        .footer { margin-top: 40px; text-align: center; font-size: 12px; color: #666; }
    </style>
</head>
<body>
    <div class="container">
        <h1>📝 Сопроводительное письмо</h1>
        <p style="color: #888">Готово к отправке на hh.ru</p>
        <div class="letter-content" id="letterText">{{ letter }}</div>
        <button class="btn-copy" onclick="copyText()">📋 Скопировать текст</button>
        <div class="footer">Powered by ResumeEasy Bot</div>
    </div>
    <script>
        function copyText() {
            navigator.clipboard.writeText(document.getElementById("letterText").innerText)
                .then(() => alert("Текст скопирован!"));
        }
    </script>
</body>
</html>
"""

ADMIN_HTML = """
<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>ResumeEasy Admin</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { background: #0a0a0a; color: #e0e0e0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
        .sidebar { position: fixed; left: 0; top: 0; width: 220px; height: 100vh; background: #111; padding: 20px; border-right: 1px solid #222; }
        .sidebar h2 { color: #bb86fc; margin-bottom: 30px; font-size: 20px; }
        .sidebar a { display: block; color: #888; text-decoration: none; padding: 10px; border-radius: 6px; margin-bottom: 5px; transition: 0.2s; }
        .sidebar a:hover, .sidebar a.active { background: #1e1e1e; color: #fff; }
        .main { margin-left: 220px; padding: 30px; }
        .stats-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 15px; margin-bottom: 30px; }
        .stat-card { background: #1e1e1e; padding: 20px; border-radius: 10px; border: 1px solid #333; }
        .stat-card .value { font-size: 32px; font-weight: bold; color: #03dac6; }
        .stat-card .label { font-size: 13px; color: #888; margin-top: 5px; }
        .chart-container { background: #1e1e1e; padding: 20px; border-radius: 10px; border: 1px solid #333; margin-bottom: 20px; }
        table { width: 100%; border-collapse: collapse; background: #1e1e1e; border-radius: 10px; overflow: hidden; }
        th { background: #252525; padding: 12px; text-align: left; font-size: 13px; color: #888; text-transform: uppercase; }
        td { padding: 12px; border-top: 1px solid #333; font-size: 14px; }
        tr:hover td { background: #252525; }
        .badge { padding: 3px 8px; border-radius: 10px; font-size: 11px; font-weight: bold; }
        .badge-new { background: #03dac6; color: #000; }
        .badge-active { background: #bb86fc; color: #000; }
    </style>
</head>
<body>
    <div class="sidebar">
        <h2>📊 ResumeEasy</h2>
        <a href="/admin" class="active">🏠 Дашборд</a>
        <a href="/admin/users">👥 Пользователи</a>
        <a href="/admin/export">📥 Экспорт CSV</a>
    </div>
    <div class="main">
        <h1 style="margin-bottom: 5px;">Дашборд</h1>
        <p style="color: #888; margin-bottom: 25px;">Обновлено: {{ now }}</p>
        <div class="stats-grid">
            <div class="stat-card"><div class="value">{{ total_users }}</div><div class="label">👥 Всего пользователей</div></div>
            <div class="stat-card"><div class="value">{{ new_today }}</div><div class="label">🆕 Новых сегодня</div></div>
            <div class="stat-card"><div class="value">{{ total_analyses }}</div><div class="label">📊 Всего анализов</div></div>
            <div class="stat-card"><div class="value">{{ active_week }}</div><div class="label">🔥 Активных за 7 дней</div></div>
        </div>
        <div class="chart-container"><canvas id="userChart" height="120"></canvas></div>
        <h2 style="margin-bottom: 15px;">Последние пользователи</h2>
        <table>
            <thead><tr><th>ID</th><th>Имя</th><th>Username</th><th>Анализов</th><th>Ср. ATS</th><th>Активность</th><th>Статус</th></tr></thead>
            <tbody>
                {% for u in users %}
                <tr>
                    <td>{{ u.user_id }}</td>
                    <td>{{ u.first_name or '—' }}</td>
                    <td>{{ u.username or '—' }}</td>
                    <td>{{ u.total }}</td>
                    <td>{{ "%.0f"|format(u.avg_ats) }}</td>
                    <td>{{ u.last_activity.strftime('%d.%m.%Y') if u.last_activity else '—' }}</td>
                    <td>{% if u.total == 0 %}<span class="badge badge-new">NEW</span>{% else %}<span class="badge badge-active">ACTIVE</span>{% endif %}</td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
    </div>
    <script>
        new Chart(document.getElementById('userChart'), {
            type: 'line',
            data: { labels: {{ chart_labels | tojson }}, datasets: [{ label: 'Новые', data: {{ chart_data | tojson }}, borderColor: '#bb86fc', backgroundColor: 'rgba(187,134,252,0.1)', fill: true, tension: 0.4 }] },
            options: { responsive: true, plugins: { legend: { display: false } }, scales: { y: { beginAtZero: true, grid: { color: '#333' } }, x: { grid: { color: '#333' } } } }
        });
    </script>
</body>
</html>
"""

ADMIN_USERS_HTML = """
<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8"><title>Users - ResumeEasy Admin</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { background: #0a0a0a; color: #e0e0e0; font-family: -apple-system, sans-serif; }
        .sidebar { position: fixed; left: 0; top: 0; width: 220px; height: 100vh; background: #111; padding: 20px; border-right: 1px solid #222; }
        .sidebar h2 { color: #bb86fc; margin-bottom: 30px; }
        .sidebar a { display: block; color: #888; text-decoration: none; padding: 10px; border-radius: 6px; margin-bottom: 5px; }
        .sidebar a:hover, .sidebar a.active { background: #1e1e1e; color: #fff; }
        .main { margin-left: 220px; padding: 30px; }
        table { width: 100%; border-collapse: collapse; background: #1e1e1e; border-radius: 10px; overflow: hidden; }
        th { background: #252525; padding: 12px; text-align: left; font-size: 13px; color: #888; }
        td { padding: 12px; border-top: 1px solid #333; font-size: 14px; }
        tr:hover td { background: #252525; }
    </style>
</head>
<body>
    <div class="sidebar">
        <h2>📊 ResumeEasy</h2>
        <a href="/admin">🏠 Дашборд</a>
        <a href="/admin/users" class="active">👥 Пользователи</a>
        <a href="/admin/export">📥 Экспорт CSV</a>
    </div>
    <div class="main">
        <h1>Все пользователи</h1>
        <table>
            <thead><tr><th>ID</th><th>Имя</th><th>Username</th><th>Дата регистрации</th><th>Активность</th><th>Анализов</th><th>Ср. ATS</th></tr></thead>
            <tbody>
                {% for u in users %}
                <tr>
                    <td>{{ u.user_id }}</td>
                    <td>{{ u.first_name or '—' }}</td>
                    <td>{{ u.username or '—' }}</td>
                    <td>{{ u.join_date.strftime('%d.%m.%Y') if u.join_date else '—' }}</td>
                    <td>{{ u.last_activity.strftime('%d.%m.%Y') if u.last_activity else '—' }}</td>
                    <td>{{ u.total }}</td>
                    <td>{{ "%.0f"|format(u.avg_ats) }}</td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
    </div>
</body>
</html>
"""
