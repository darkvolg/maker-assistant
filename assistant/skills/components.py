"""SQLite inventory with atomic consumption and an undo journal."""
import json
import re
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from assistant.skills.registry import registry

_path = Path("data/inventory.sqlite3")
_lock = threading.RLock()
_selected = None


def configure(config):
    global _path, _selected
    _path = Path(config["skills"]["components"]["storage_path"])
    _selected = None


def normalize(text):
    text = text.lower().replace(",", ".").replace("ё", "е")
    text = re.sub(r"(\d+(?:\.\d+)?)\s*(?:килоом\w*|ком|kohm|kω|k)(?![a-zа-я])", r"\1k", text)
    text = re.sub(r"(\d+)k(\d+)\b", r"\1.\2k", text)
    text = re.sub(r"резистор\w*|resistors?", "resistor", text)
    text = re.sub(r"конденсатор\w*|capacitors?", "capacitor", text)
    return re.findall(r"[a-zа-я0-9]+(?:\.[0-9]+)?", text)


@contextmanager
def _connect():
    _path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(_path, timeout=10)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    db.executescript("""
      CREATE TABLE IF NOT EXISTS components (
        id INTEGER PRIMARY KEY, name TEXT NOT NULL, category TEXT NOT NULL DEFAULT '',
        package TEXT NOT NULL DEFAULT '', qty INTEGER NOT NULL CHECK(qty>=0), location TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS movements (
        id INTEGER PRIMARY KEY, component_id INTEGER NOT NULL REFERENCES components(id),
        count INTEGER NOT NULL CHECK(count>0), project TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, undone INTEGER NOT NULL DEFAULT 0);
    """)
    try:
        with db:
            yield db
    finally:
        db.close()


def import_inventory(path):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    rows = data["components"]
    if not isinstance(rows, list) or not rows:
        raise ValueError("Список компонентов пуст")
    for row in rows:
        if type(row.get("qty")) is not int or row["qty"] < 0 or not row.get("name"):
            raise ValueError("Нужны название и неотрицательный целый остаток")
    with _lock, _connect() as db:
        db.execute("BEGIN IMMEDIATE")
        if db.execute("SELECT count(*) FROM components").fetchone()[0]:
            raise ValueError("Импорт разрешён только в пустую базу")
        db.executemany("INSERT INTO components(name,category,package,qty,location) VALUES(?,?,?,?,?)",
            [(r["name"], r.get("category", ""), r.get("package", ""), r["qty"], r.get("location", "")) for r in rows])
    return len(rows)


def _matches(db, query):
    tokens = normalize(query)
    if not tokens:
        raise ValueError("Уточни название или номинал детали")
    rows = db.execute("SELECT * FROM components ORDER BY id").fetchall()
    return [r for r in rows if all(any((t == word if any(c.isdigit() for c in t) and not any(c.isalpha() for c in t.rstrip("k")) else t in word) for word in normalize(
        " ".join([r["name"], r["category"], r["package"]]))) for t in tokens)]


@registry.register("check_component", "Найти деталь по названию, номиналу и корпусу. Например: 10k 0805.")
def check_component(query: str) -> str:
    global _selected
    with _lock, _connect() as db:
        rows = _matches(db, query)
        _selected = rows[0]["id"] if len(rows) == 1 else None
        if not rows:
            return f"Деталь '{query}' не найдена."
        result = " ".join(f"{r['name']} ({r['package']}): {r['qty']} шт., {r['location']}." for r in rows[:5])
        if len(rows) > 1:
            result += f" Найдено вариантов: {len(rows)}. Уточни деталь перед списанием."
        return result


@registry.register("consume_component", "Списать детали. Пустой query означает последнюю однозначно найденную деталь.", mutating=True)
def consume_component(query: str = "", count: int = 1, project: str = "текущий проект") -> str:
    if type(count) is not int or not 1 <= count <= 1000000:
        raise ValueError("Количество должно быть целым числом от 1 до 1000000")
    with _lock, _connect() as db:
        db.execute("BEGIN IMMEDIATE")
        rows = _matches(db, query) if query.strip() else db.execute("SELECT * FROM components WHERE id=?", (_selected,)).fetchall()
        if len(rows) != 1:
            return "Уточни деталь: нужен один однозначный результат поиска."
        row = rows[0]
        if row["qty"] < count:
            return f"Недостаточно деталей: в наличии {row['qty']} шт."
        db.execute("UPDATE components SET qty=qty-? WHERE id=?", (count, row["id"]))
        db.execute("INSERT INTO movements(component_id,count,project) VALUES(?,?,?)", (row["id"], count, project))
        return f"Списано {count} шт. {row['name']}. Осталось {row['qty']-count}."


@registry.register("undo_consumption", "Отменить последнее неотменённое списание деталей.", mutating=True)
def undo_consumption() -> str:
    with _lock, _connect() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT * FROM movements WHERE undone=0 ORDER BY id DESC LIMIT 1").fetchone()
        if row is None:
            return "Нет списаний для отмены."
        db.execute("UPDATE components SET qty=qty+? WHERE id=?", (row["count"], row["component_id"]))
        db.execute("UPDATE movements SET undone=1 WHERE id=?", (row["id"],))
        return f"Списание отменено. Возвращено {row['count']} шт."
