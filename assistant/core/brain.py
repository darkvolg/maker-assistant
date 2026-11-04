"""Local commands first; LLM for flexible language and conversation."""
import json
import re
import time
import requests
from assistant.skills.registry import registry

NUMBERS = {"один":1,"одну":1,"одна":1,"два":2,"две":2,"три":3,"четыре":4,"пять":5,"десять":10}


class Brain:
    def __init__(self, config):
        cfg = config.get("brain", {})
        self.provider = cfg.get("provider", "ollama")
        self.model = cfg.get("model", "qwen2.5:7b-instruct")
        self.base_url = cfg.get("base_url", "http://127.0.0.1:11434/v1")
        self.api_key = cfg.get("api_key", "ollama")
        self.timeout = cfg.get("timeout_sec", 60)
        self.history = []
        self.pending = None
        self.confirm_seconds = 45

    def _action(self, name, args):
        try:
            args = registry.validate(name, args)
            if registry.is_mutating(name):
                self.pending = (name, args, time.monotonic())
                labels = {"consume_component":"Списать детали", "undo_consumption":"Вернуть последнее списание",
                          "ha_turn_on":"Включить устройство", "ha_turn_off":"Выключить устройство",
                          "git_commit_push":"Закоммитить и отправить подготовленные изменения", "create_github_issue":"Создать задачу GitHub"}
                fields = {"query":"деталь", "count":"количество", "project":"проект", "entity_id":"устройство", "message":"сообщение", "title":"заголовок", "body":"описание"}
                details = ", ".join(f"{fields.get(k,k)}: {v}" for k,v in args.items() if v != "")
                summary = labels.get(name, name) + "." + (" " + details + "." if details else "")
                return f"{summary} Подтверди: «подтверждаю», или скажи «отмена»."
            return registry.execute(name, args)
        except (ValueError, TypeError) as exc:
            return f"Действие не выполнено: {exc}"

    def process(self, query):
        query = query.strip()
        q = query.lower().strip(" .!?")
        if self.pending and time.monotonic() - self.pending[2] > self.confirm_seconds:
            self.pending = None
        if q in ("подтверждаю", "подтвердить", "confirm"):
            if not self.pending:
                return "Нет команды для подтверждения. Повтори запрос."
            name, args, _ = self.pending
            self.pending = None
            result = registry.execute(name, args)
            self.history.extend([{"role":"user","content":query},{"role":"assistant","content":result}])
            self.history = self.history[-12:]
            return result
        if q in ("отмена", "cancel", "нет"):
            self.pending = None
            return "Ожидающая команда отменена."
        # Any new request supersedes the previous pending action.
        self.pending = None
        result = self._local(q)
        if result is None:
            result = self._ask_model(query)
        self.history.extend([{"role":"user","content":query},{"role":"assistant","content":result}])
        self.history = self.history[-12:]
        return result

    def _local(self, q):
        if q in ("отмени", "отмени списание", "верни последнее списание", "undo"):
            return self._action("undo_consumption", {})
        if q in ("который час", "сколько времени", "время", "what time is it"):
            return self._action("get_time", {})
        if q in ("статус git", "git status", "статус гит"):
            return self._action("git_status", {})
        search = re.match(r"^(?:где|найди|есть ли|проверь склад|find)\s+(.+)$", q)
        if search:
            term = re.sub(r"\b(?:у нас|на складе|в наличии)\b", "", search[1]).strip()
            return self._action("check_component", {"query":term})
        consumption = re.match(r"^(?:спиши|взял|взяла|возьми|consume)\s+(-?\d+|один|одну|одна|два|две|три|четыре|пять|десять)\b(.*)$", q)
        if consumption:
            n = consumption[1]
            count = NUMBERS[n] if n in NUMBERS else int(n)
            if count <= 0:
                return "Количество должно быть положительным целым числом."
            term = re.sub(r"^\s*(?:штук[аи]?|шт\.?|детал[ьи])\b", "", consumption[2]).strip()
            parts = re.split(r"\s+для проекта\s+", term, maxsplit=1)
            return self._action("consume_component", {"query":parts[0], "count":count,
                "project":parts[1] if len(parts)>1 else "текущий проект"})
        timer = re.match(r"^(?:поставь\s+)?таймер(?:\s+на)?\s+(\d+)\s*(секунд\w*|минут\w*|час\w*)(?:\s+(.+))?$", q)
        if timer:
            mult = 60 if timer[2].startswith("мин") else 3600 if timer[2].startswith("час") else 1
            return self._action("set_timer", {"seconds":int(timer[1])*mult, "message":timer[3] or "Время вышло"})
        return None

    def _ask_model(self, query):
        if self.provider == "none":
            return "Команда не распознана. Примеры: «найди ESP32», «взял 2», «таймер на 5 минут»."
        prompt = ("Ты помощник в мастерской. Отвечай кратко на языке пользователя. "
            "Не утверждай, что действие выполнено: для действий возвращай только JSON "
            '{"action":"имя","arguments":{}}. Для обычного вопроса верни текст. '
            "Не выдумывай устройства и остатки. Если данных недостаточно, уточни. "
            "Не вызывай действие, если пользователь лишь обсуждает его или просит объяснить. "
            "Доступные инструменты:\n" + registry.get_skill_descriptions())
        payload = {"model":self.model, "messages":[{"role":"system","content":prompt},
                   *self.history, {"role":"user","content":query}], "temperature":0.1, "max_tokens":256}
        try:
            resp = requests.post(self.base_url.rstrip("/")+"/chat/completions", json=payload,
                headers={"Authorization":f"Bearer {self.api_key}"}, timeout=(3,self.timeout))
            resp.raise_for_status()
            text = resp.json()["choices"][0]["message"]["content"].strip()
        except (requests.RequestException, KeyError, TypeError, ValueError):
            return "Модель недоступна. Базовые команды склада, времени и таймеров продолжают работать. Проверь doctor."
        text = re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()
        candidate = re.sub(r"^```(?:json)?\s*|\s*```$", "", text).strip()
        if candidate.startswith("{"):
            try:
                data = json.loads(candidate)
                if not isinstance(data, dict) or set(data) - {"action","arguments","thought"}:
                    raise ValueError()
                return self._action(data["action"], data.get("arguments",{}))
            except (ValueError, TypeError, KeyError):
                return "Модель вернула некорректную команду; ничего не выполнено. Повтори запрос."
        return text or "Модель вернула пустой ответ."
