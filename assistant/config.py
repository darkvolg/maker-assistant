import os
from pathlib import Path
from typing import Any, Dict
import yaml
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent

def load_config(config_path: str = "config.yaml") -> Dict[str, Any]:
    full_path = BASE_DIR / config_path
    if not full_path.exists():
        raise FileNotFoundError(f"Config file not found: {full_path}")
    
    with open(full_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f) or {}

    # Override with env variables if present
    if os.getenv("DEEPSEEK_API_KEY"):
        config.setdefault("brain", {})["api_key"] = os.getenv("DEEPSEEK_API_KEY")
        if config["brain"].get("provider") == "deepseek":
            config["brain"]["base_url"] = "https://api.deepseek.com/v1"
            
    if os.getenv("OPENAI_API_KEY") and config.get("brain", {}).get("provider") == "openai":
        config.setdefault("brain", {})["api_key"] = os.getenv("OPENAI_API_KEY")

    return config
