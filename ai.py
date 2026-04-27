import requests
from config import DEEPSEEK_API_KEY, logger

def analyze_part(resume_text, part_name, timeout=60, custom_prompt=None, job_desc=None):
    url = "https://api.deepseek.com/v1/chat/completions"
    headers = {"Authorization": f"Bearer {DEEPSEEK_API_KEY}", "Content-Type": "application/json"}
    job_text = job_desc if job_desc else "Не указана"
    
    prompts = {
        "full_report": f"""Ты — старший HR-рекрутер и эксперт по ATS с 10+ лет опыта в России.
Проанализируй резюме и верни СТРОГО JSON со следующей структурой:

{{
  "overall_score": 0-100,
  "ats_score": 0-100,
  "keywords": ["ключевое слово 1", "ключевое слово 2"],
  "headlines": ["Заголовок 1", "Заголовок 2", "Заголовок 3"],
  "critical_fixes": [
    {{"title": "Краткий заголовок", "description": "Конкретное описание", "done": false}}
  ],
  "metrics_fixes": [
    {{"title": "Краткий заголовок", "description": "Конкретное описание", "done": false}}
  ],
  "style_fixes": [
    {{"title": "Краткий заголовок", "description": "Конкретное описание", "done": false}}
  ],
  "hh_recommendations": "Советы",
  "match_vacancies": ["Вакансия 1", "Вакансия 2"],
  "verdict": "Общий вердикт"
}}

ВАЖНЫЕ ПРАВИЛА:
- НЕ придирайся к формату дат (например "настоящее время", "по настоящее время"). Это стандарт hh.ru, он правильный.
- НЕ придирайся к автоматическим подписям hh.ru вроде "Резюме обновлено", "Дата рождения", "Гражданство".
- Обращай внимание ТОЛЬКО на реальные разрывы в опыте работы (если между работами больше 2 месяцев).
- НЕ предлагай добавить разделы, которые УЖЕ ЕСТЬ в резюме ("Образование", "Навыки", "Обо мне", "Опыт вождения", "Знание языков"). Внимательно прочитай ВЕСЬ текст резюме перед тем как писать об отсутствии раздела.
- critical_fixes: ТОЛЬКО реальные проблемы ATS (нестандартные заголовки разделов, отсутствие ключевых слов в навыках, проблемы с форматированием). Минимум 2.
- metrics_fixes: где добавить цифры, проценты, рубли. Минимум 2.
- style_fixes: язык, глаголы, вода. Минимум 2.
- description — КОНКРЕТНЫЙ пример из резюме: что именно заменить и на что.

Резюме:
{resume_text[:4000]}""",
        
        "job_match": f"""Сравни резюме с вакансией. Верни СТРОГО JSON:
{{
  "match_percent": 0-100,
  "missing_skills": ["skill1", "skill2"],
  "recommendations": ["rec1", "rec2"],
  "summary": "Краткий итог на 2 предложения"
}}

Резюме:
{resume_text[:2000]}

Вакансия:
{job_text[:2000]}""",

        "cover_letter": f"""Ты — старший HR-рекрутер. Напиши короткое, ударное сопроводительное письмо для hh.ru.
- 5-10 предложений.
- Первое предложение: имя, должность, ключевой результат.
- 3-4 буллита с достижениями.
- Живой язык, без штампов.
- НЕ пиши "Резюме прилагаю".
- НЕ используй Markdown.

Резюме:
{resume_text[:3000]}

Вакансия:
{job_text[:3000]}"""
    }
    
    payload = {
        "model": "deepseek-chat", 
        "messages": [{"role": "user", "content": custom_prompt or prompts.get(part_name, "")}], 
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
