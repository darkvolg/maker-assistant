"""Import this module in assistant/cli.py to enable the example."""
from assistant.skills.registry import registry

@registry.register("calculate_resistor_power", "Мощность на резисторе по напряжению и сопротивлению.")
def calculate_resistor_power(voltage: float, resistance: float) -> str:
    if resistance <= 0:
        raise ValueError("Сопротивление должно быть положительным")
    return f"Рассеиваемая мощность: {voltage ** 2 / resistance:.3f} Вт."
