import re
import requests
from assistant.skills.registry import registry

_config = {}

def configure(config):
    global _config
    _config = config.get("skills", {}).get("smart_home", {})


def _control(entity_id, service):
    if not re.fullmatch(r"(?:light|switch|fan|media_player)\.[a-z0-9_]+", entity_id):
        return "Неверное устройство: нужны light.*, switch.*, fan.* или media_player.*"
    if entity_id not in _config.get("allowed_entities", []):
        return "Устройство отсутствует в smart_home.allowed_entities. Действие не выполнено."
    url, token = _config.get("ha_url"), _config.get("ha_token")
    if not url or not token:
        return "Home Assistant не настроен. Действие не выполнено."
    try:
        response = requests.post(f"{url.rstrip('/')}/api/services/{entity_id.split('.')[0]}/{service}",
            json={"entity_id":entity_id}, headers={"Authorization":f"Bearer {token}"}, timeout=(3,10))
        response.raise_for_status()
        return f"Home Assistant принял команду {service} для {entity_id}."
    except requests.RequestException:
        return "Home Assistant не подтвердил команду. Проверь подключение и токен."


@registry.register("ha_turn_on", "Включить разрешённое устройство Home Assistant по entity_id.", mutating=True)
def ha_turn_on(entity_id: str) -> str:
    return _control(entity_id, "turn_on")


@registry.register("ha_turn_off", "Выключить разрешённое устройство Home Assistant по entity_id.", mutating=True)
def ha_turn_off(entity_id: str) -> str:
    return _control(entity_id, "turn_off")
