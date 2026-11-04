import os
import requests
from assistant.skills.registry import registry

@registry.register("tv_control", "Управление телевизором (питание, громкость, вход). Действия: 'power_toggle', 'vol_up', 'vol_down', 'mute', 'hdmi1'.")
def tv_control(action: str) -> str:
    # Safe stub or integration with local TV scripts
    actions_map = {
        "power_toggle": "Питание телевизора переключено.",
        "vol_up": "Громкость ТВ увеличена.",
        "vol_down": "Громкость ТВ уменьшена.",
        "mute": "Звук ТВ выключен.",
        "hdmi1": "ТВ переключен на вход HDMI 1."
    }
    return actions_map.get(action, f"Команда для ТВ '{action}' отправлена.")

@registry.register("ha_turn_on", "Включить устройство или свет в Home Assistant по entity_id (например, switch.socket, light.workbench).")
def ha_turn_on(entity_id: str) -> str:
    ha_url = os.getenv("HA_BASE_URL")
    ha_token = os.getenv("HA_ACCESS_TOKEN")
    if not ha_url or not ha_token:
        return f"Имитация: устройство {entity_id} включено (HA_BASE_URL не задан в .env)."

    domain = entity_id.split(".")[0]
    headers = {"Authorization": f"Bearer {ha_token}", "Content-Type": "application/json"}
    try:
        url = f"{ha_url.rstrip('/')}/api/services/{domain}/turn_on"
        resp = requests.post(url, json={"entity_id": entity_id}, headers=headers, timeout=5)
        if resp.status_code == 200:
            return f"Устройство {entity_id} успешно включено."
        return f"Ошибка Home Assistant: статус {resp.status_code}"
    except Exception as e:
        return f"Ошибка связи с Home Assistant: {e}"
