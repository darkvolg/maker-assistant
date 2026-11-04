import inspect
import json
import logging
from typing import Callable, Dict, Any, List

logger = logging.getLogger("maker_assistant.skills")

class SkillRegistry:
    def __init__(self):
        self._skills: Dict[str, Dict[str, Any]] = {}

    def register(self, name: str, description: str):
        """Decorator to register an action skill."""
        def decorator(func: Callable):
            sig = inspect.signature(func)
            params = {}
            for p_name, param in sig.parameters.items():
                if p_name in ("self", "ctx"):
                    continue
                p_type = "string"
                if param.annotation == int:
                    p_type = "integer"
                elif param.annotation == float:
                    p_type = "number"
                elif param.annotation == bool:
                    p_type = "boolean"
                params[p_name] = {
                    "type": p_type,
                    "default": None if param.default == inspect.Parameter.empty else param.default
                }

            self._skills[name] = {
                "name": name,
                "description": description,
                "parameters": params,
                "func": func
            }
            return func
        return decorator

    def get_skill_descriptions(self) -> str:
        """Returns clean description of all registered skills for the LLM prompt."""
        lines = []
        for name, meta in self._skills.items():
            params_str = ", ".join([f"{k}: {v['type']}" for k, v in meta["parameters"].items()])
            lines.append(f"- {name}({params_str}): {meta['description']}")
        return "\n".join(lines)

    def execute(self, action_name: str, arguments: Dict[str, Any]) -> str:
        if action_name not in self._skills:
            return f"Error: Unknown action '{action_name}'"

        func = self._skills[action_name]["func"]
        try:
            result = func(**arguments)
            return str(result)
        except Exception as e:
            logger.error(f"Error executing {action_name}: {e}")
            return f"Execution error: {e}"


registry = SkillRegistry()
