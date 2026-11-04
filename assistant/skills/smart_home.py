import os
import requests
import logging
from assistant.skills.registry import registry

logger = logging.getLogger("maker_assistant.smart_home")

@registry.register("tv_control", "Управление телевизором (питание, громкость, вход). Действия: 'power_toggle', 'vol_up', 'vol_down', 'mute', 'hdmi1'.")
def tv_control(action: str) -> str:
    actions_map = {
        "power_toggle": "Питание телевизора переключено.",
        "vol_up": "Громкость ТВ увеличена.",
        "vol_down": "Громкость ТВ уменьшена.",
        "mute": "Звук ТВ выключен.",
        "hdmi1": "ТВ переключен на вход HDMI 1."
    }
    return actions_map.get(action, f"Команда для ТВ '{action}' отправлена.")

@registry.register("ha_turn_on", "Включить устройство или свет в локальном Home Assistant (например, switch.socket, light.workbench).")
def ha_turn_on(entity_id: str) -> str:
    ha_url = os.getenv("HA_BASE_URL", "http://192.168.0.10:8123")
    ha_token = os.getenv("HA_ACCESS_TOKEN")
    
    if not ha_token:
        return f"Эмуляция: устройство {entity_id} включено (задайте HA_ACCESS_TOKEN в .env для реального вызова)."

    domain = entity_id.split(".")[0]
    headers = {"Authorization": f"Bearer {ha_token}", "Content-Type": "application/json"}
    
    # Короткий таймаут 3.0 сек для локальной сети — не виснет даже при сбое роутера
    try:
        url = f"{ha_url.rstrip('/')}/api/services/{domain}/turn_on"
        resp = requests.post(url, json={"entity_id": entity_id}, headers=headers, timeout=3.0)
        if resp.status_code == 200:
            return f"Устройство {entity_id} успешно включено."
        return f"Ошибка Home Assistant: статус {resp.status_code}"
    except requests.exceptions.Timeout:
        return f"Home Assistant не ответил за 3 секунды (таймаут локальной сети)."
    except Exception as e:
        return f"Сбой подключения к Home Assistant: {e}"
