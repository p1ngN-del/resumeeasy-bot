# templates_landing.py — ОРИГИНАЛЬНЫЙ ДИЗАЙН САЙТА (как был до сегодня)

LANDING_HTML = """
<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>ResumeEasy — ATS-проверка резюме</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: linear-gradient(135deg, #0a0a1a 0%, #1a1a2e 50%, #0a0a1a 100%);
            min-height: 100vh;
            display: flex;
            justify-content: center;
            align-items: center;
            padding: 20px;
        }
        .container {
            background: rgba(255,255,255,0.05);
            backdrop-filter: blur(10px);
            border: 1px solid rgba(255,255,255,0.1);
            border-radius: 24px;
            padding: 40px;
            max-width: 600px;
            width: 100%;
            box-shadow: 0 20px 60px rgba(0,0,0,0.5);
            text-align: center;
        }
        .logo { font-size: 48px; margin-bottom: 10px; }
        h1 { color: #fff; font-size: 28px; font-weight: 700; margin-bottom: 8px; }
        .subtitle { color: #8892b0; font-size: 16px; margin-bottom: 30px; }
        .upload-area {
            border: 2px dashed rgba(255,255,255,0.2);
            border-radius: 16px;
            padding: 40px 20px;
            cursor: pointer;
            transition: all 0.3s ease;
            background: rgba(255,255,255,0.03);
        }
        .upload-area:hover { border-color: #64ffda; background: rgba(100,255,218,0.05); }
        .upload-area.dragover { border-color: #64ffda; background: rgba(100,255,218,0.1); }
        .upload-area .icon { font-size: 48px; margin-bottom: 12px; }
        .upload-area p { color: #ccd6f6; font-size: 14px; }
        .upload-area .hint { color: #8892b0; font-size: 12px; margin-top: 8px; }
        #fileInput { display: none; }
        .progress-section { display: none; margin-top: 24px; text-align: left; }
        .progress-section.active { display: block; }
        .stage-text { color: #ccd6f6; font-size: 14px; margin-bottom: 8px; }
        .progress-bar-bg { width: 100%; height: 6px; background: rgba(255,255,255,0.1); border-radius: 3px; overflow: hidden; }
        .progress-bar-fill { height: 100%; width: 0%; background: linear-gradient(90deg, #64ffda, #00b4d8); border-radius: 3px; transition: width 0.5s ease; }
        .progress-status { color: #64ffda; font-size: 13px; margin-top: 6px; }
        .error-text { color: #ff6b6b; font-size: 14px; margin-top: 12px; }
        .features {
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 16px;
            margin-top: 30px;
        }
        .feature { background: rgba(255,255,255,0.05); border-radius: 12px; padding: 16px 12px; text-align: center; }
        .feature .icon { font-size: 24px; margin-bottom: 6px; }
        .feature h4 { color: #fff; font-size: 13px; margin-bottom: 4px; }
        .feature p { color: #8892b0; font-size: 11px; }
        .badge { display: inline-block; background: rgba(100,255,218,0.15); color: #64ffda; padding: 4px 12px; border-radius: 20px; font-size: 12px; margin-top: 4px; }
        @media (max-width: 600px) { .features { grid-template-columns: 1fr; } .container { padding: 24px; } h1 { font-size: 22px; } }
    </style>
</head>
<body>
    <div class="container">
        <div class="logo">📄</div>
        <h1>ResumeEasy</h1>
        <p class="subtitle">Ваше резюме глазами ATS-робота</p>

        <div class="upload-area" id="dropZone">
            <div class="icon">📤</div>
            <p><strong>Перетащите PDF-резюме сюда</strong></p>
            <p style="margin-top:6px;color:#8892b0;">или нажмите, чтобы выбрать файл (до 10 МБ)</p>
            <div class="hint">📎 Поддерживаются только PDF</div>
        </div>
        <input type="file" id="fileInput" accept=".pdf">

        <div class="progress-section" id="progressSection">
            <div class="stage-text" id="stageText">⏳ Подготовка...</div>
            <div class="progress-bar-bg">
                <div class="progress-bar-fill" id="progressFill"></div>
            </div>
            <div class="progress-status" id="progressStatus">0%</div>
        </div>

        <div class="error-text" id="errorText"></div>

        <div class="features">
            <div class="feature">
                <div class="icon">🔍</div>
                <h4>ATS-совместимость</h4>
                <p>Проверка под hh.ru</p>
                <span class="badge">⭐ ТОП-10 слов</span>
            </div>
            <div class="feature">
                <div class="icon">📋</div>
                <h4>Чек-лист правок</h4>
                <p>6+ конкретных улучшений</p>
                <span class="badge">⚡ 30 сек</span>
            </div>
            <div class="feature">
                <div class="icon">✨</div>
                <h4>Улучшенное резюме</h4>
                <p>Готовая версия</p>
                <span class="badge">✅ 1 клик</span>
            </div>
        </div>
    </div>

    <script>
    const dropZone = document.getElementById('dropZone');
    const fileInput = document.getElementById('fileInput');
    const progressSection = document.getElementById('progressSection');
    const progressFill = document.getElementById('progressFill');
    const progressStatus = document.getElementById('progressStatus');
    const stageText = document.getElementById('stageText');
    const errorText = document.getElementById('errorText');

    dropZone.addEventListener('click', function() {
        fileInput.click();
    });

    dropZone.addEventListener('dragover', function(e) {
        e.preventDefault();
        dropZone.classList.add('dragover');
    });

    dropZone.addEventListener('dragleave', function() {
        dropZone.classList.remove('dragover');
    });

    dropZone.addEventListener('drop', function(e) {
        e.preventDefault();
        dropZone.classList.remove('dragover');
        if (e.dataTransfer.files.length) {
            handleFile(e.dataTransfer.files[0]);
        }
    });

    fileInput.addEventListener('change', function(e) {
        if (e.target.files.length) {
            handleFile(e.target.files[0]);
        }
    });

    function handleFile(file) {
        errorText.textContent = '';

        if (!file.name.toLowerCase().endsWith('.pdf')) {
            errorText.textContent = '❌ Пожалуйста, загрузите файл в формате PDF.';
            return;
        }

        if (file.size > 10 * 1024 * 1024) {
            errorText.textContent = '❌ Файл больше 10 МБ. Пожалуйста, уменьшите размер.';
            return;
        }

        progressSection.classList.add('active');
        updateProgress(0, '⏳ Начинаю анализ...');

        var formData = new FormData();
        formData.append('file', file);

        fetch('/api/analyze-stream', {
            method: 'POST',
            body: formData
        }).then(function(response) {
            var reader = response.body.getReader();
            var decoder = new TextDecoder();

            function readStream() {
                reader.read().then(function(result) {
                    if (result.done) {
                        if (!window._redirected) {
                            updateProgress(0, '❌ Ошибка: сервер не вернул результат');
                        }
                        return;
                    }
                    var chunk = decoder.decode(result.value);
                    var lines = chunk.split('\n');
                    for (var i = 0; i < lines.length; i++) {
                        var line = lines[i];
                        if (line.startsWith('data: ')) {
                            try {
                                var data = JSON.parse(line.slice(6));
                                if (data.stage !== undefined) {
                                    updateProgress(data.progress || 0, data.stage);
                                }
                                if (data.redirect) {
                                    window._redirected = true;
                                    window.location.href = data.redirect;
                                }
                                if (data.error) {
                                    updateProgress(0, '❌ ' + data.error);
                                    errorText.textContent = '❌ ' + data.error;
                                }
                            } catch (e) {
                                console.warn('Parse error:', e);
                            }
                        }
                    }
                    readStream();
                });
            }
            readStream();
        }).catch(function(err) {
            console.error('Fetch error:', err);
            updateProgress(0, '❌ Ошибка соединения с сервером');
            errorText.textContent = '❌ Ошибка соединения с сервером. Попробуйте позже.';
        });
    }

    function updateProgress(percent, text) {
        progressFill.style.width = percent + '%';
        progressStatus.textContent = Math.round(percent) + '%';
        stageText.textContent = text;
    }
</script>
</body>
</html>
"""
