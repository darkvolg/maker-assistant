import subprocess
import logging
from pathlib import Path
from typing import Optional, List
from assistant.skills.registry import registry

logger = logging.getLogger("maker_assistant.github_tools")

def _run_safe_cmd(cmd: List[str], cwd: Optional[str] = None, timeout: int = 10) -> tuple[int, str]:
    """Строго безопасное выполнение системных команд без shell=True для исключения инъекций."""
    try:
        res = subprocess.run(
            cmd,
            cwd=cwd,
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
def git_status(repo_path: str = ".") -> str:
    code, out = _run_safe_cmd(["git", "status", "-s"], cwd=repo_path, timeout=5)
    if code != 0:
        return f"Ошибка git: {out}"
    if not out:
        return "В репозитории нет незакоммиченных изменений, всё чисто."
    lines = [line.strip() for line in out.splitlines() if line.strip()]
    return f"Изменено файлов: {len(lines)}. Последние: {', '.join(lines[:3])}."

@registry.register("git_commit_push", "Зафиксировать (commit) все изменения и отправить (push) их на GitHub с указанным комментарием.")
def git_commit_push(message: str, repo_path: str = ".") -> str:
    if not message:
        message = "Update project files via Maker Assistant"

    # 1. git add .
    code_add, out_add = _run_safe_cmd(["git", "add", "."], cwd=repo_path, timeout=10)
    if code_add != 0:
        return f"Ошибка при git add: {out_add}"

    # 2. git commit с параметризованным аргументом (безопасно от инъекций)
    code_commit, out_commit = _run_safe_cmd(["git", "commit", "-m", message], cwd=repo_path, timeout=10)
    if code_commit != 0 and "nothing to commit" in out_commit.lower():
        return "Нет новых изменений для коммита."

    # 3. git push
    code_push, out_push = _run_safe_cmd(["git", "push"], cwd=repo_path, timeout=20)
    if code_push != 0:
        return f"Коммит создан, но push завершился с ошибкой: {out_push}"

    return f"Изменения успешно закоммичены и отправлены на GitHub с сообщением: '{message}'."

@registry.register("create_github_issue", "Создать задачу (Issue) в репозитории на GitHub с заголовком и описанием.")
def create_github_issue(title: str, body: str = "") -> str:
    cmd = ["gh", "issue", "create", "--title", title, "--body", body or title]
    code, out = _run_safe_cmd(cmd, timeout=15)
    if code == 0:
        return f"Задача успешно создана на GitHub: {title}."
    return f"Не удалось создать задачу через GitHub CLI: {out}"
