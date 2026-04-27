import requests
from config import DEEPSEEK_API_KEY, logger

def analyze_part(resume_text, part_name, timeout=60, custom_prompt=None, job_desc=None):
    url = "https://api.deepseek.com/v1/chat/completions"
    headers = {"Authorization": f"Bearer {DEEPSEEK_API_KEY}", "Content-Type": "application/json"}
    job_text = job_desc if job_desc else "Не указана"
    
    prompts = {
        "full_report": f"""Ты — старший HR-рекрутер и эксперт по ATS с 10+ лет опыта в России.
Проанализируй ВСЁ резюме полностью и верни СТРОГО JSON:

{{
  "overall_score": 0-100,
  "ats_score": 0-100,
  "keywords": ["ключевое слово 1", "ключевое слово 2"],
  "headlines": ["Заголовок 1", "Заголовок 2", "Заголовок 3"],
  "critical_fixes": [{{"title": "Краткий заголовок", "description": "Конкретное описание", "done": false}}],
  "metrics_fixes": [{{"title": "Краткий заголовок", "description": "Конкретное описание", "done": false}}],
  "style_fixes": [{{"title": "Краткий заголовок", "description": "Конкретное описание", "done": false}}],
  "hh_recommendations": "Советы",
  "match_vacancies": ["Вакансия 1", "Вакансия 2"],
  "verdict": "Общий вердикт"
}}

ЖЁСТКИЕ ПРАВИЛА (нарушать нельзя):
1. ФОРМАТ ДАТ: "настоящее время", "по настоящее время", "Present" — это СТАНДАРТ hh.ru. НЕ ПРИДИРАЙСЯ К ДАТАМ ВООБЩЕ. Игнорируй любые нестандартные написания дат — это автоматическое форматирование hh.ru.
2. КОНТАКТЫ: телефон в скобках "+7 (XXX) XXXXXXX", "Телеграмм:", двоеточия после меток — это стандарт hh.ru. НЕ трогай формат контактов.
3. СЛУЧАЙНЫЕ СИМВОЛЫ: если видишь "?" после email или другие одиночные символы — это баг парсинга PDF, ИГНОРИРУЙ.
4. ДУБЛИРОВАНИЕ: если блок повторяется дважды — это баг парсинга PDF, анализируй только один раз.
5. НЕ предлагай добавить разделы которые уже есть: Образование, Навыки, Обо мне, Опыт вождения, Знание языков. ПРОЧИТАЙ ВСЁ РЕЗЮМЕ ДО КОНЦА перед тем как писать об отсутствии раздела.
6. critical_fixes: ТОЛЬКО реальные ATS-проблемы (заголовки, структура). Минимум 2.
7. metrics_fixes: где добавить цифры, бюджет, проценты. Минимум 2.
8. style_fixes: язык, глаголы, вода. Минимум 2.

ВСЁ РЕЗЮМЕ (читай до конца):
{resume_text}""",
        
        "job_match": f"""Сравни резюме с вакансией. Верни СТРОГО JSON:
{{
  "match_percent": 0-100,
  "missing_skills": ["skill1", "skill2"],
  "recommendations": ["rec1", "rec2"],
  "summary": "Краткий итог на 2 предложения"
}}

ВСЁ РЕЗЮМЕ:
{resume_text}

ВАКАНСИЯ:
{job_text}""",

        "cover_letter": f"""Ты — старший HR-рекрутер. Напиши короткое сопроводительное письмо ОТ ИМЕНИ КАНДИДАТА для отклика на конкретную вакансию.

СТРУКТУРА ПИСЬМА:
1. Первое предложение: имя кандидата, желаемая должность, ключевое достижение в цифрах, релевантное вакансии.
2. 2-3 предложения: почему кандидат подходит именно под эту вакансию (сравни навыки из резюме с требованиями вакансии).
3. 1-2 предложения: что кандидат может дать компании на этой позиции (конкретный результат).
4. Контакты для связи.

ПРАВИЛА:
- Письмо ДОЛЖНО отвечать на вопрос "почему я подхожу на ЭТУ вакансию", а не просто пересказывать резюме.
- Если вакансия НЕ УКАЗАНА — напиши универсальное письмо без привязки к конкретной должности.
- НЕ используй фразы "Я идеальный кандидат", "Я лучший", "Я уверен".
- Живой, деловой язык. Без штампов.
- НЕ пиши "Резюме прилагаю" и "С уважением".
- НЕ используй Markdown.
- Максимум 10 предложений.

ВАКАНСИЯ (если "Не указана" — игнорируй):
{job_text}

РЕЗЮМЕ КАНДИДАТА:
{resume_text}"""
    }
    
    prompt_text = custom_prompt or prompts.get(part_name, "")
    if len(prompt_text) > 90000:
        logger.warning(f"Prompt too long ({len(prompt_text)} chars), truncating")
        prompt_text = prompt_text[:90000] + "\n\n[Резюме обрезано из-за большого размера]"
    
    payload = {
        "model": "deepseek-chat", 
        "messages": [{"role": "user", "content": prompt_text}], 
        "temperature": 0.2, 
        "max_tokens": 4000
    }
    try:
        r = requests.post(url, headers=headers, json=payload, timeout=timeout)
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        logger.error(f"AI Error: {e}")
        return None