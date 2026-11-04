import os
import json
from pathlib import Path
from typing import Optional
from assistant.skills.registry import registry

DEFAULT_STORAGE_FILE = Path(__file__).resolve().parent.parent.parent / "examples" / "sklad_example.json"

def _load_storage(filepath: Optional[str] = None):
    p = Path(filepath) if filepath else DEFAULT_STORAGE_FILE
    if not p.exists():
        return {"components": []}
    try:
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"components": []}

def _save_storage(data, filepath: Optional[str] = None):
    p = Path(filepath) if filepath else DEFAULT_STORAGE_FILE
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

@registry.register("check_component", "Найти радиодеталь на складе по названию или номиналу. Возвращает количество и место хранения.")
def check_component(query: str) -> str:
    data = _load_storage()
    query_lower = query.lower().strip()
    matches = []
    
    for item in data.get("components", []):
        name = item.get("name", "").lower()
        category = item.get("category", "").lower()
        package = item.get("package", "").lower()
        if query_lower in name or query_lower in category or query_lower in package:
            matches.append(item)

    if not matches:
        return f"Компонент '{query}' не найден на складе."

    res = []
    for m in matches[:3]:
        res.append(f"{m.get('name')} ({m.get('package', '')}): {m.get('qty', 0)} шт. в {m.get('location', 'не указано')}.")
    return " ".join(res)

@registry.register("consume_component", "Списать (уменьшить) количество деталей на складе при использовании в проекте.")
def consume_component(query: str, count: int = 1, project: str = "текущий проект") -> str:
    data = _load_storage()
    query_lower = query.lower().strip()
    
    for item in data.get("components", []):
        name = item.get("name", "").lower()
        if query_lower in name:
            current_qty = item.get("qty", 0)
            if current_qty < count:
                return f"Недостаточно деталей '{item.get('name')}': в наличии только {current_qty} шт."
            item["qty"] = current_qty - count
            item["last_project"] = project
            _save_storage(data)
            return f"Списано {count} шт. '{item.get('name')}'. Осталось {item['qty']} шт. в {item.get('location')}."

    return f"Компонент '{query}' не найден для списания."
