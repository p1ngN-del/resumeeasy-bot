REPORT_HTML = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Резюме — полный разбор</title>
    <!-- Google Fonts для современного шрифта -->
    <link href="https://fonts.googleapis.com/css2?family=Inter:opsz@14..32&display=swap" rel="stylesheet">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'Inter', sans-serif;
            background: #0b0b1a;
            color: #e0e0e0;
            display: flex;
            justify-content: center;
            padding: 30px 20px;
            min-height: 100vh;
        }
        .container {
            max-width: 820px;
            width: 100%;
            background: #14142b;
            border-radius: 28px;
            padding: 35px 30px;
            box-shadow: 0 20px 60px rgba(0,0,0,0.7);
            border: 1px solid rgba(255,255,255,0.06);
        }
        /* Заголовки, карточки, сетки */
        h1 {
            font-size: 28px;
            font-weight: 700;
            color: #ffffff;
            margin-bottom: 6px;
            display: flex;
            align-items: center;
            gap: 10px;
        }
        .subhead {
            color: #8a8aa8;
            font-size: 15px;
            border-bottom: 1px solid #2a2a4a;
            padding-bottom: 18px;
            margin-bottom: 28px;
            display: flex;
            justify-content: space-between;
            flex-wrap: wrap;
        }
        .score-grid {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 16px;
            margin-bottom: 32px;
        }
        .score-card {
            background: #1d1d3a;
            border-radius: 18px;
            padding: 18px 20px;
            text-align: center;
            border: 1px solid #2a2a50;
        }
        .score-card .number {
            font-size: 36px;
            font-weight: 700;
            letter-spacing: -0.5px;
        }
        .score-card .label {
            font-size: 13px;
            color: #9a9ac0;
            margin-top: 4px;
        }
        .progress-ring {
            width: 70px;
            height: 70px;
            border-radius: 50%;
            background: conic-gradient(#4f8cf7 var(--pct, 0%), #2a2a50 var(--pct, 0%));
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 20px;
            font-weight: 700;
            color: #fff;
            margin: 0 auto 8px;
        }
        .section {
            margin: 28px 0 16px;
        }
        .section h2 {
            font-size: 20px;
            font-weight: 600;
            color: #fff;
            margin-bottom: 12px;
            display: flex;
            align-items: center;
            gap: 10px;
        }
        .section h2 span {
            background: #2a2a4a;
            padding: 2px 12px;
            border-radius: 40px;
            font-size: 13px;
            font-weight: 400;
            color: #b0b0d0;
        }
        .tag-group {
            display: flex;
            flex-wrap: wrap;
            gap: 8px;
            margin: 6px 0 12px;
        }
        .tag {
            background: #25254a;
            padding: 6px 16px;
            border-radius: 30px;
            font-size: 14px;
            color: #c8c8f0;
            border: 1px solid #353560;
        }
        .fix-item {
            background: #1a1a36;
            border-radius: 14px;
            padding: 14px 18px;
            margin-bottom: 10px;
            border-left: 4px solid #4f8cf7;
            display: flex;
            gap: 12px;
            align-items: flex-start;
        }
        .fix-item .icon {
            font-size: 20px;
            margin-top: 2px;
        }
        .fix-item .content {
            flex: 1;
        }
        .fix-item .content .title {
            font-weight: 600;
            color: #fff;
        }
        .fix-item .content .desc {
            color: #b0b0d0;
            font-size: 14px;
            margin-top: 3px;
        }
        .vacancy-list {
            display: flex;
            flex-wrap: wrap;
            gap: 12px;
            margin: 8px 0;
        }
        .vacancy-item {
            background: #1a1a38;
            padding: 8px 18px;
            border-radius: 30px;
            border: 1px solid #33335a;
            font-size: 14px;
        }
        .verdict-box {
            background: #1d1d3e;
            border-radius: 18px;
            padding: 18px 22px;
            margin: 20px 0 8px;
            border: 1px solid #2e2e58;
            font-size: 15px;
            line-height: 1.6;
        }
        .footer-meta {
            margin-top: 30px;
            padding-top: 16px;
            border-top: 1px solid #222244;
            font-size: 13px;
            color: #6a6a92;
            display: flex;
            justify-content: space-between;
            flex-wrap: wrap;
        }
        @media (max-width: 600px) {
            .score-grid { grid-template-columns: 1fr; }
            .container { padding: 20px 16px; }
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>📄 Резюме — полный разбор</h1>
        <div class="subhead">
            <span>📅 {{ date }}</span>
            <span>⚡ ID: {{ report_id[:8] }}</span>
        </div>

        <!-- Блок с оценками -->
        <div class="score-grid">
            <div class="score-card">
                <div class="progress-ring" style="--pct: {{ ats }}%;">
                    {{ ats }}
                </div>
                <div class="label">🤖 ATS-совместимость</div>
                <div style="font-size:13px; color:#7a7aaa; margin-top:6px;">Оценка парсинга hh.ru</div>
            </div>
            <div class="score-card">
                <div class="progress-ring" style="--pct: {{ overall }}%;">
                    {{ overall }}
                </div>
                <div class="label">📊 Общая оценка контента</div>
                <div style="font-size:13px; color:#7a7aaa; margin-top:6px;">Сила текста и структура</div>
            </div>
        </div>

        <!-- Ключевые слова -->
        <div class="section">
            <h2>🔑 Ключевые слова <span>ATS-ready</span></h2>
            <div class="tag-group">
                {% for kw in keywords %}
                    <span class="tag">{{ kw }}</span>
                {% endfor %}
            </div>
        </div>

        <!-- Варианты заголовков -->
        {% if headlines %}
        <div class="section">
            <h2>🏷️ Варианты заголовка</h2>
            <ul style="list-style: none; padding: 0;">
                {% for h in headlines %}
                    <li style="background: #181835; padding: 10px 16px; border-radius: 12px; margin-bottom: 6px; border-left: 3px solid #4f8cf7;">{{ h }}</li>
                {% endfor %}
            </ul>
        </div>
        {% endif %}

        <!-- Правки -->
        <div class="section">
            <h2>🔧 Чек-лист правок</h2>
            
            {% if critical_fixes %}
            <div style="margin: 12px 0 8px; font-weight: 600; color: #f28b82;">Критические</div>
            {% for fix in critical_fixes %}
            <div class="fix-item">
                <div class="icon">⚠️</div>
                <div class="content">
                    <div class="title">{{ fix.title }}</div>
                    <div class="desc">{{ fix.description }}</div>
                </div>
            </div>
            {% endfor %}
            {% endif %}

            {% if metrics_fixes %}
            <div style="margin: 12px 0 8px; font-weight: 600; color: #fdbc6b;">Метрики и цифры</div>
            {% for fix in metrics_fixes %}
            <div class="fix-item" style="border-left-color: #fdbc6b;">
                <div class="icon">📊</div>
                <div class="content">
                    <div class="title">{{ fix.title }}</div>
                    <div class="desc">{{ fix.description }}</div>
                </div>
            </div>
            {% endfor %}
            {% endif %}

            {% if style_fixes %}
            <div style="margin: 12px 0 8px; font-weight: 600; color: #81c995;">Стиль и формулировки</div>
            {% for fix in style_fixes %}
            <div class="fix-item" style="border-left-color: #81c995;">
                <div class="icon">✏️</div>
                <div class="content">
                    <div class="title">{{ fix.title }}</div>
                    <div class="desc">{{ fix.description }}</div>
                </div>
            </div>
            {% endfor %}
            {% endif %}
        </div>

        <!-- Рекомендации по hh.ru -->
        {% if hh_rec %}
        <div class="section">
            <h2>📌 Рекомендации по загрузке на hh.ru</h2>
            <div style="background: #181838; padding: 16px 20px; border-radius: 16px; white-space: pre-wrap; line-height: 1.7;">
                {{ hh_rec }}
            </div>
        </div>
        {% endif %}

        <!-- Целевые вакансии -->
        {% if match_vac %}
        <div class="section">
            <h2>🎯 Подходящие вакансии</h2>
            <div class="vacancy-list">
                {% for vac in match_vac %}
                    <span class="vacancy-item">{{ vac }}</span>
                {% endfor %}
            </div>
        </div>
        {% endif %}

        <!-- Вердикт -->
        <div class="section">
            <h2>📋 Финальный вердикт</h2>
            <div class="verdict-box">
                {{ verdict }}
            </div>
        </div>

        <div class="footer-meta">
            <span>🤖 ResumeEasy — ATS-эксперт</span>
            <span>🧠 Анализ проведён {{ date }}</span>
        </div>
    </div>
</body>
</html>
"""
