import inspect
from assistant.i18n import tr

class SkillRegistry:
    def __init__(self):
        self._skills = {}
        self.disabled = set()

    def register(self, name, description, mutating=False):
        def decorator(func):
            self._skills[name] = dict(func=func, description=description, mutating=mutating)
            return func
        return decorator

    def configure(self, config):
        self.disabled = {name for name, meta in self._skills.items()
            if not config.get("skills", {}).get(meta["func"].__module__.split(".")[-1], {}).get("enabled", True)}

    def validate(self, name, arguments):
        if name not in self._skills or name in self.disabled:
            raise ValueError(tr(f"Навык недоступен: {name}", f"Skill unavailable: {name}"))
        if not isinstance(arguments, dict):
            raise ValueError(tr("Аргументы должны быть объектом", "Arguments must be an object"))
        sig = inspect.signature(self._skills[name]["func"])
        bound = sig.bind(**arguments)
        bound.apply_defaults()
        for key, value in bound.arguments.items():
            expected = sig.parameters[key].annotation
            if expected in (str, int, bool, float) and type(value) is not expected:
                raise ValueError(tr(f"Неверный тип параметра {key}", f"Invalid type for parameter {key}"))
        return dict(bound.arguments)

    def get_skill_descriptions(self):
        return "\n".join(f"- {name}{inspect.signature(m['func'])}: {m['description']}"
                         for name, m in self._skills.items() if name not in self.disabled)

    def is_mutating(self, name):
        return self._skills[name]["mutating"]

    def execute(self, name, arguments):
        try:
            args = self.validate(name, arguments)
            return str(self._skills[name]["func"](**args))
        except Exception as exc:
            return tr(f"Действие не выполнено: {exc}", f"Action failed: {exc}")

registry = SkillRegistry()
