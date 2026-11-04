"""
Пример: Как добавить свой навык за 5 строк кода!
"""

from assistant.skills.registry import registry

@registry.register("toggle_soldering_iron", "Включить или выключить умную розетку паяльника на рабочем месте.")
def toggle_soldering_iron(state: str) -> str:
    # Здесь может быть запрос к розетке Tuya / Sonoff / ESPHome
    if state.lower() in ("on", "вкл", "включи"):
        return "Паяльник включен. Не забудьте выключить после работы!"
    else:
        return "Паяльник обесточен."
