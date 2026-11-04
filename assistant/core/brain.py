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
        
        # Резервный локальный Ollama URL на случай сбоя облака
        self.local_ollama_url = "http://127.0.0.1:11434/v1"

    def _call_llm_api(self, base_url: str, model: str, api_key: str, payload: dict) -> Tuple[bool, str]:
        """Вызывает LLM endpoint с жесткими таймаутами (2.0 сек подключение, 8.0 сек ответ)."""
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}"
        }
        endpoint = f"{base_url.rstrip('/')}/chat/completions"
        try:
            resp = requests.post(endpoint, json=payload, headers=headers, timeout=(2.0, 8.0))
            if resp.status_code == 200:
                raw_text = resp.json()["choices"][0]["message"]["content"].strip()
                return True, raw_text
            else:
                logger.warning(f"LLM API returned status {resp.status_code} at {endpoint}")
                return False, f"API Error: {resp.status_code}"
        except Exception as e:
            logger.warning(f"Connection failed to {endpoint}: {e}")
            return False, str(e)

    def process(self, user_query: str) -> str:
        """
        Обрабатывает запрос с каскадом отказоустойчивости:
        1. Основной провайдер (Cloud/Ollama) ->
        2. Резервный локальный Ollama ->
        3. Локальные rule-based навыки без сети.
        """
        skills_doc = registry.get_skill_descriptions()
        system_prompt = SYSTEM_PROMPT_TEMPLATE.format(skills=skills_doc)

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_query}
            ],
            "temperature": self.temperature
        }

        # 1. Попытка через основной настроенный провайдер
        success, raw_text = self._call_llm_api(self.base_url, self.model, self.api_key, payload)

        # 2. Если основной провайдер (например, облачный DeepSeek) упал, пробуем локальный Ollama
        if not success and self.provider != "ollama":
            logger.info("Cloud LLM unavailable. Falling back to local Ollama instance...")
            payload["model"] = "qwen2.5:7b"  # Дефолтная локальная модель
            success, raw_text = self._call_llm_api(self.local_ollama_url, "qwen2.5:7b", "ollama", payload)

        # 3. Если сеть полностью отсутствует и LLM оффлайн — моментальный локальный парсер
        if not success:
            logger.info("All LLM endpoints offline. Executing offline rule-based fallback.")
            return self._fallback_rule_based(user_query)

        # Проверка и выполнение JSON действий
        return self._execute_action_or_text(raw_text)

    def _execute_action_or_text(self, raw_text: str) -> str:
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

    def _fallback_rule_based(self, query: str) -> str:
        """100% автономный офлайн-обработчик без LLM."""
        q = query.lower()
        if "время" in q or "который час" in q:
            return registry.execute("get_time", {})
        if "склад" in q or "найди" in q or "есть ли" in q:
            words = [w for w in q.split() if len(w) > 3 and w not in ("найди", "есть", "склад", "наличии")]
            term = " ".join(words) if words else "esp32"
            return registry.execute("check_component", {"query": term})
        if "статус" in q and ("гит" in q or "git" in q):
            return registry.execute("git_status", {})
        if "телевизор" in q or "тв" in q:
            return registry.execute("tv_control", {"action": "power_toggle"})
        return f"Запрос: '{query}'. Локальный интеллект выполнил базовую проверку."
