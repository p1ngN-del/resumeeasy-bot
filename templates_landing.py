LANDING_HTML = r"""
<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>ResumeEasy — Проверка резюме на ATS</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { 
            background: #0a0a0a; 
            color: #e0e0e0; 
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; 
            line-height: 1.6; 
            overflow-x: hidden;
        }
        .hero { 
            min-height: 100vh; 
            display: flex; 
            flex-direction: column; 
            justify-content: center; 
            align-items: center; 
            text-align: center; 
            padding: 40px 20px;
            background: radial-gradient(ellipse at center, #1a1a2e 0%, #0a0a0a 70%);
        }
        .hero h1 { 
            font-size: clamp(2rem, 5vw, 3.5rem); 
            color: #fff; 
            margin-bottom: 20px; 
            max-width: 800px; 
        }
        .hero .highlight { color: #bb86fc; }
        .hero p { 
            font-size: 1.2rem; 
            color: #aaa; 
            max-width: 600px; 
            margin-bottom: 40px; 
        }
        .upload-zone {
            border: 2px dashed #333;
            border-radius: 16px;
            padding: 60px 40px;
            text-align: center;
            cursor: pointer;
            transition: all 0.3s;
            max-width: 500px;
            width: 100%;
            margin: 0 auto;
            background: #111;
        }
        .upload-zone:hover, .upload-zone.drag-over {
            border-color: #bb86fc;
            background: #1a1a2e;
            transform: scale(1.02);
        }
        .upload-zone .icon { font-size: 48px; margin-bottom: 15px; }
        .upload-zone .text { color: #aaa; font-size: 1rem; }
        .upload-zone .subtext { color: #666; font-size: 0.85rem; margin-top: 8px; }
        .upload-zone input { display: none; }
        
        .status { margin-top: 20px; display: none; }
        .status.active { display: block; }
        .progress-bar { 
            width: 100%; 
            height: 6px; 
            background: #333; 
            border-radius: 3px; 
            overflow: hidden; 
            margin-top: 10px; 
        }
        .progress-fill { 
            height: 100%; 
            width: 0%; 
            background: linear-gradient(90deg, #bb86fc, #03dac6); 
            transition: width 0.3s; 
        }
        
        .steps {
            padding: 80px 20px;
            max-width: 900px;
            margin: 0 auto;
        }
        .steps h2 { text-align: center; color: #fff; margin-bottom: 50px; font-size: 2rem; }
        .steps-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 30px;
        }
        .step-card {
            background: #1e1e1e;
            padding: 30px;
            border-radius: 12px;
            text-align: center;
            border: 1px solid #333;
        }
        .step-card .num {
            display: inline-block;
            width: 50px;
            height: 50px;
            background: #bb86fc;
            color: #000;
            border-radius: 50%;
            line-height: 50px;
            font-weight: bold;
            font-size: 1.4rem;
            margin-bottom: 15px;
        }
        .step-card h3 { color: #fff; margin-bottom: 10px; }
        .step-card p { color: #aaa; font-size: 0.95rem; }
        
        .footer { text-align: center; padding: 40px 20px; color: #666; font-size: 0.85rem; border-top: 1px solid #222; }
        .footer a { color: #bb86fc; text-decoration: none; }
        
        @media (max-width: 600px) {
            .hero h1 { font-size: 1.8rem; }
            .upload-zone { padding: 40px 20px; }
        }
    </style>
</head>
<body>
    <section class="hero">
        <h1>Проверьте резюме на <span class="highlight">ATS-совместимость</span> за 30 секунд</h1>
        <p>80% резюме отсеиваются роботами до того, как их увидит HR. Узнайте, пройдёт ли ваше.</p>
        
        <div class="upload-zone" id="uploadZone">
            <div class="icon">📤</div>
            <div class="text">Перетащите PDF-резюме сюда</div>
            <div class="subtext">или нажмите, чтобы выбрать файл (до 10 МБ)</div>
            <input type="file" id="fileInput" accept=".pdf">
        </div>
        
        <div class="status" id="status">
            <p id="statusText">⏳ Анализируем резюме...</p>
            <div class="progress-bar"><div class="progress-fill" id="progressFill"></div></div>
        </div>
    </section>

    <section class="steps">
        <h2>Как это работает</h2>
        <div class="steps-grid">
            <div class="step-card">
                <div class="num">1</div>
                <h3>Загружаете PDF</h3>
                <p>Перетащите файл или выберите его на устройстве. Ваше резюме в полной безопасности.</p>
            </div>
            <div class="step-card">
                <div class="num">2</div>
                <h3>AI анализирует</h3>
                <p>Нейросеть проверяет резюме на совместимость с ATS-системами (hh.ru, Workday).</p>
            </div>
            <div class="step-card">
                <div class="num">3</div>
                <h3>Получаете отчёт</h3>
                <p>Чек-лист правок, улучшенное резюме и сопроводительное письмо — всё готово для отклика.</p>
            </div>
        </div>
    </section>

    <div class="footer">
        <p>© 2026 <a href="https://t.me/your_bot" target="_blank">ResumeEasy Bot</a> — Ваш персональный ATS-эксперт</p>
    </div>

    <script>
        const zone = document.getElementById('uploadZone');
        const input = document.getElementById('fileInput');
        const status = document.getElementById('status');
        const statusText = document.getElementById('statusText');
        const progressFill = document.getElementById('progressFill');

        zone.addEventListener('click', () => input.click());
        zone.addEventListener('dragover', (e) => { e.preventDefault(); zone.classList.add('drag-over'); });
        zone.addEventListener('dragleave', () => zone.classList.remove('drag-over'));
        zone.addEventListener('drop', (e) => {
            e.preventDefault();
            zone.classList.remove('drag-over');
            handleFile(e.dataTransfer.files[0]);
        });
        input.addEventListener('change', (e) => handleFile(e.target.files[0]));

        function handleFile(file) {
            if (!file) return;
            if (!file.name.toLowerCase().endsWith('.pdf')) {
                alert('Принимаются только PDF файлы');
                return;
            }
            if (file.size > 10 * 1024 * 1024) {
                alert('Файл больше 10 МБ');
                return;
            }
            uploadFile(file);
        }

        async function uploadFile(file) {
            status.classList.add('active');
            statusText.innerText = '⏳ Анализируем резюме...';
            progressFill.style.width = '30%';

            const formData = new FormData();
            formData.append('file', file);

            try {
                progressFill.style.width = '60%';
                const response = await fetch('/api/analyze', { method: 'POST', body: formData });
                progressFill.style.width = '90%';
                const data = await response.json();
                
                if (data.redirect) {
                    progressFill.style.width = '100%';
                    statusText.innerText = '✅ Анализ готов! Переадресация...';
                    setTimeout(() => { window.location.href = data.redirect; }, 500);
                } else {
                    statusText.innerText = '❌ ' + (data.error || 'Ошибка');
                    progressFill.style.width = '0%';
                }
            } catch (err) {
                statusText.innerText = '❌ Ошибка соединения. Попробуйте ещё раз.';
                progressFill.style.width = '0%';
            }
        }
    </script>
</body>
</html>
"""
