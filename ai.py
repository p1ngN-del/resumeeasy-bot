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

ПРАВИЛА:
1. НЕ придирайся к форматированию hh.ru: телефон в скобках, "Телеграмм:", "настоящее время" — это стандарт.
2. Игнорируй случайные символы вроде "?" после email — это баг парсинга PDF.
3. НЕ предлагай добавить разделы, которые УЖЕ ЕСТЬ. Прочитай ВСЁ резюме до конца.
4. critical_fixes: ТОЛЬКО реальные ATS-проблемы. Минимум 2.
5. metrics_fixes: где добавить цифры, бюджет, проценты. Минимум 2.
6. style_fixes: язык, глаголы, вода. Минимум 2.

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

        "cover_letter": f"""Ты — старший HR-рекрутер. Напиши короткое сопроводительное письмо.
- 5-10 предложений.
- Живой язык, без штампов.
- НЕ пиши "Резюме прилагаю".
- НЕ используй Markdown.

ВСЁ РЕЗЮМЕ:
{resume_text}

ВАКАНСИЯ:
{job_text}"""
    }
    
    # Если текст слишком длинный — режем до максимума контекста DeepSeek (128K токенов ≈ 100K символов)
    prompt_text = custom_prompt or prompts.get(part_name, "")
    if len(prompt_text) > 90000:
        logger.warning(f"Prompt too long ({len(prompt_text)} chars), truncating resume")
        # Обрезаем только если совсем огромный
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
