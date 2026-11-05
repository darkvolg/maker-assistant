import os
from pathlib import Path
import yaml
from dotenv import load_dotenv


def _merge(target, source):
    for key, value in source.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            _merge(target[key], value)
        else:
            target[key] = value


def load_config(config_path="config.yaml"):
    path = Path(config_path).expanduser().resolve()
    load_dotenv(path.parent / ".env", override=False)
    config = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    local = path.with_name(path.stem + ".local" + path.suffix)
    if local.exists() and local != path:
        _merge(config, yaml.safe_load(local.read_text(encoding="utf-8")) or {})
    brain = config.setdefault("brain", {})
    key = {"deepseek": "DEEPSEEK_API_KEY", "openai": "OPENAI_API_KEY"}.get(brain.get("provider", "ollama"))
    if key and os.getenv(key):
        brain["api_key"] = os.environ[key]
    skills = config.setdefault("skills", {})
    components = skills.setdefault("components", {})
    components["storage_path"] = str((path.parent / components.get("storage_path", "data/inventory.sqlite3")).resolve())
    git = skills.setdefault("github_tools", {})
    git["repo_path"] = str((path.parent / git.get("repo_path", ".")).resolve())
    ha = skills.setdefault("smart_home", {})
    ha["ha_url"] = os.getenv("HA_BASE_URL", ha.get("ha_url", ""))
    ha["ha_token"] = os.getenv("HA_ACCESS_TOKEN", ha.get("ha_token", ""))
    if config.get("tts", {}).get("engine", "sapi") not in ("sapi", "edge-tts", "console"):
        raise ValueError("tts.engine: выбери sapi, edge-tts или console")
    if config.get("audio", {}).get("sample_rate", 16000) != 16000:
        raise ValueError("Whisper требует audio.sample_rate: 16000")
    return config
