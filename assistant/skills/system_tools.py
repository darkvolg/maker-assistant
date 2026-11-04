import datetime
import threading
import time
from assistant.skills.registry import registry

_active_timers = []

@registry.register("get_time", "Узнать точное текущее время и дату.")
def get_time() -> str:
    now = datetime.datetime.now()
    return f"Сейчас {now.strftime('%H:%M')}, {now.strftime('%d.%m.%Y')}."

@registry.register("set_timer", "Поставить таймер в секундах или минутах с напоминанием (например, остывание платы или окончание травления).")
def set_timer(seconds: int, message: str = "Время вышло") -> str:
    def _timer_worker():
        time.sleep(seconds)
        print(f"\n🔔 [ТАЙМЕР]: {message}!\n")

    t = threading.Thread(target=_timer_worker, daemon=True)
    t.start()
    _active_timers.append(t)
    mins = seconds // 60
    secs = seconds % 60
    time_str = f"{mins} мин " if mins > 0 else ""
    time_str += f"{secs} сек"
    return f"Таймер на {time_str} установлен: {message}."
