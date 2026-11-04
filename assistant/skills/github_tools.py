import subprocess
import logging
from pathlib import Path
from typing import Optional, List
from assistant.skills.registry import registry

logger = logging.getLogger("maker_assistant.github_tools")
_repo_path = str(Path.cwd())

def configure(config):
    global _repo_path
    _repo_path = config["skills"]["github_tools"]["repo_path"]

def _run_safe_cmd(cmd: List[str], cwd: Optional[str] = None, timeout: int = 10) -> tuple[int, str]:
    """Строго безопасное выполнение системных команд без shell=True для исключения инъекций."""
    try:
        res = subprocess.run(
            cmd,
            cwd=cwd or _repo_path,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            shell=False,       # Защита от Command Injection!
            timeout=timeout    # Защита от зависания процесса
        )
        out = (res.stdout + " " + res.stderr).strip()
        return res.returncode, out
    except subprocess.TimeoutExpired:
        return 1, f"Таймаут выполнения команды ({timeout} сек)"
    except Exception as e:
        return 1, str(e)

@registry.register("git_status", "Проверить статус изменений в локальном git-репозитории проекта (измененные файлы, ветка).")
def git_status() -> str:
    code, out = _run_safe_cmd(["git", "status", "-s"], cwd=_repo_path, timeout=5)
    if code != 0:
        return f"Ошибка git: {out}"
    if not out:
        return "В репозитории нет незакоммиченных изменений, всё чисто."
    lines = [line.strip() for line in out.splitlines() if line.strip()]
    return f"Изменено файлов: {len(lines)}. Последние: {', '.join(lines[:3])}."

@registry.register("git_commit_push", "Закоммитить только заранее подготовленные (staged) изменения и отправить их на GitHub.", mutating=True)
def git_commit_push(message: str) -> str:
    if not message:
        message = "Update project files via Maker Assistant"

    code, staged = _run_safe_cmd(["git", "diff", "--cached", "--name-only"], timeout=5)
    if code != 0:
        return f"Ошибка git: {staged}"
    if not staged:
        return "Нет подготовленных изменений. Сначала выбери файлы через git add."

    # 2. git commit с параметризованным аргументом (безопасно от инъекций)
    code_commit, out_commit = _run_safe_cmd(["git", "commit", "-m", message], cwd=_repo_path, timeout=10)
    if code_commit != 0 and "nothing to commit" in out_commit.lower():
        return "Нет новых изменений для коммита."

    if code_commit != 0:
        return f"Коммит не создан: {out_commit}"

    # 3. git push
    code_push, out_push = _run_safe_cmd(["git", "push"], cwd=_repo_path, timeout=20)
    if code_push != 0:
        return f"Коммит создан, но push завершился с ошибкой: {out_push}"

    return f"Изменения успешно закоммичены и отправлены на GitHub с сообщением: '{message}'."

@registry.register("create_github_issue", "Создать задачу GitHub в настроенном репозитории.", mutating=True)
def create_github_issue(title: str, body: str = "") -> str:
    cmd = ["gh", "issue", "create", "--title", title, "--body", body or title]
    code, out = _run_safe_cmd(cmd, timeout=15)
    if code == 0:
        return f"Задача успешно создана на GitHub: {title}."
    return f"Не удалось создать задачу через GitHub CLI: {out}"
