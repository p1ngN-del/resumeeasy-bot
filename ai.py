import requests
import json
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
  "keywords": ["найденные", "ключевые", "слова"],
  "headlines": ["Заголовок 1", "Заголовок 2", "Заголовок 3"],
  "critical_fixes": [
    {{"title": "Краткий заголовок проблемы", "description": "Конкретное описание, что заменить и как. Например: замените 'Моя история' на 'Опыт работы'.", "done": false}}
  ],
  "metrics_fixes": [
    {{"title": "Краткий заголовок", "description": "Конкретное описание с примером цифр. Например: вместо 'повысил продажи' напишите 'увеличил продажи на 35%'.", "done": false}}
  ],
  "style_fixes": [
    {{"title": "Краткий заголовок", "description": "Конкретное описание стилистической правки.", "done": false}}
  ],
  "hh_recommendations": "Советы по заполнению hh.ru",
  "match_vacancies": ["Вакансия 1", "Вакансия 2"],
  "verdict": "Общий вердикт"
}}

Важно:
- critical_fixes: минимум 2 проблемы ATS (заголовки, формат, отсутствие разделов)
- metrics_fixes: минимум 2 места где добавить цифры
- style_fixes: минимум 2 стилистических правки
- description ВСЕГДА конкретный — покажи на примере из резюме, что именно заменить

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
Требования:
- 5-10 предложений.
- Первое предложение: имя, должность, ключевой результат.
- 3-4 буллита с достижениями под вакансию.
- Живой язык, без штампов.
- В конце: контакты.
- НЕ пиши "Резюме прилагаю".
- НЕ используй Markdown-разметку, только чистый текст.

Резюме:
{resume_text[:3000]}

Вакансия:
{job_text[:3000]}""",

        "improve_blocks": f"""Ты — эксперт по улучшению резюме. Примени указанные правки к резюме и верни СТРОГО JSON с разбивкой по блокам:

{{
  "blocks": [
    {{
      "title": "Заголовок",
      "old_text": "исходный текст блока",
      "new_text": "улучшенный текст блока",
      "changes": "что изменилось (одно предложение)"
    }},
    {{
      "title": "Контакты",
      "old_text": "исходный текст",
      "new_text": "улучшенный текст",
      "changes": "что изменилось"
    }},
    {{
      "title": "Опыт работы",
      "old_text": "исходный текст",
      "new_text": "улучшенный текст с метриками и цифрами",
      "changes": "какие правки применены"
    }},
    {{
      "title": "Навыки",
      "old_text": "исходный текст",
      "new_text": "улучшенный текст с ключевыми словами",
      "changes": "какие навыки добавлены"
    }},
    {{
      "title": "Образование",
      "old_text": "исходный текст",
      "new_text": "улучшенный текст",
      "changes": "что изменилось"
    }}
  ],
  "summary": "Краткий итог: что улучшено, на сколько баллов примерно выросло"
}}

Правки для применения:
{fixes_text}

Исходное резюме:
{resume_text}

Верни ПОЛНЫЙ JSON со ВСЕМИ блоками. Если какого-то блока нет в резюме — оставь old_text пустым."""
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
