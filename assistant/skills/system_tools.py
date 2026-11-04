import datetime
import threading
import time
import logging
from typing import Optional, Callable
from assistant.skills.registry import registry

logger = logging.getLogger("maker_assistant.system_tools")

_active_timers = []
_notify_callback: Optional[Callable[[str], None]] = None

def set_tts_notifier(callback: Callable[[str], None]):
    """Устанавливает коллбэк для голосового оповещения таймеров через общую очередь TTS."""
    global _notify_callback
    _notify_callback = callback

@registry.register("get_time", "Узнать точное текущее время и дату.")
def get_time() -> str:
    now = datetime.datetime.now()
    return f"Сейчас {now.strftime('%H:%M')}, {now.strftime('%d.%m.%Y')}."

@registry.register("set_timer", "Поставить таймер в секундах или минутах с напоминанием (охлаждение платы, травление).")
def set_timer(seconds: int, message: str = "Время вышло") -> str:
    if type(seconds) is not int or not 1 <= seconds <= 86400:
        raise ValueError("Таймер: от 1 до 86400 секунд")
    _active_timers[:] = [t for t in _active_timers if t.is_alive()]
    if len(_active_timers) >= 20:
        return "Уже запущено 20 таймеров."

    def _timer_worker():
        time.sleep(seconds)
        alert_text = f"Внимание! Таймер сработал: {message}."
        print(f"\n🔔 [ТАЙМЕР]: {alert_text}\n")
        
        # Голосовое оповещение через единую очередь TTS (без перебивания)
        if _notify_callback:
            _notify_callback(alert_text)

    t = threading.Thread(target=_timer_worker, daemon=True)
    t.start()
    _active_timers.append(t)
    
    mins = seconds // 60
    secs = seconds % 60
    time_str = f"{mins} мин " if mins > 0 else ""
    time_str += f"{secs} сек"
    return f"Таймер на {time_str} установлен: {message}."
