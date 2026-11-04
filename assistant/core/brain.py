import json
import logging
import re
import requests
from typing import Dict, Any, Tuple
from assistant.skills.registry import registry

logger = logging.getLogger("maker_assistant.brain")

SYSTEM_PROMPT_TEMPLATE = """Ты — голосовой ассистент инженера и мейкера на рабочем месте.
Твоя задача — помогать инженеру, пока его руки заняты работой.
Отвечай кратко, емко, естественным разговорным языком (без таблиц и сложных символов), так как твой ответ будет озвучен через динамики.

У тебя есть доступ к следующим инструментам:
{skills}

Если запрос требует действия (проверить склад, списать деталь, включить свет, поставить таймер и т.д.), верни JSON строго в таком формате:
```json
{{
  "action": "<название_инструмента>",
  "arguments": {{
    "<параметр>": "<значение>"
  }},
  "thought": "<краткое пояснение>"
}}
```

Если действие не требуется или это просто вопрос/диалог, верни ответ простым текстом без JSON блока.
"""

class Brain:
    def __init__(self, config: Dict[str, Any]):
        brain_cfg = config.get("brain", {})
        self.provider = brain_cfg.get("provider", "ollama")
        self.model = brain_cfg.get("model", "qwen2.5:7b")
        self.base_url = brain_cfg.get("base_url", "http://localhost:11434/v1")
        self.api_key = brain_cfg.get("api_key", "ollama")
        self.temperature = brain_cfg.get("temperature", 0.2)

    def process(self, user_query: str) -> str:
        """
        Processes user query through LLM, executes skills if required,
        and returns final response text ready for TTS.
        """
        skills_doc = registry.get_skill_descriptions()
        system_prompt = SYSTEM_PROMPT_TEMPLATE.format(skills=skills_doc)

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_query}
            ],
            "temperature": self.temperature
        }

        endpoint = f"{self.base_url.rstrip('/')}/chat/completions"

        try:
            resp = requests.post(endpoint, json=payload, headers=headers, timeout=20)
            if resp.status_code != 200:
                logger.error(f"Brain API error: {resp.status_code} - {resp.text}")
                return "Извините, не удалось связаться с языковой моделью."

            raw_text = resp.json()["choices"][0]["message"]["content"].strip()

            # Check if JSON action was returned
            action_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw_text, re.DOTALL)
            if not action_match and raw_text.startswith("{") and raw_text.endswith("}"):
                action_json_str = raw_text
            elif action_match:
                action_json_str = action_match.group(1)
            else:
                action_json_str = None

            if action_json_str:
                try:
                    action_data = json.loads(action_json_str)
                    action_name = action_data.get("action")
                    args = action_data.get("arguments", {})
                    logger.info(f"Executing skill: {action_name} with {args}")
                    result = registry.execute(action_name, args)
                    return result
                except Exception as ex:
                    logger.warning(f"Failed to parse skill JSON: {ex}")

            return raw_text

        except requests.exceptions.ConnectionError:
            # Fallback if Ollama/LLM server is not launched
            logger.warning("LLM server is offline. Using local rule-based fallback.")
            return self._fallback_rule_based(user_query)
        except Exception as e:
            logger.error(f"Brain exception: {e}")
            return "Произошла ошибка при обработке запроса."

    def _fallback_rule_based(self, query: str) -> str:
        """Simple rule fallback if local LLM is not running."""
        q = query.lower()
        if "время" in q or "который час" in q:
            return registry.execute("get_time", {})
        if "склад" in q or "найди" in q or "есть ли" in q:
            # extract word
            words = [w for w in q.split() if len(w) > 3 and w not in ("найди", "есть", "склад", "наличии")]
            term = " ".join(words) if words else "esp32"
            return registry.execute("check_component", {"query": term})
        if "телевизор" in q or "тв" in q:
            return registry.execute("tv_control", {"action": "power_toggle"})
        return f"Запрос принят: '{query}', но сервер локальной нейросети пока не запущен."
