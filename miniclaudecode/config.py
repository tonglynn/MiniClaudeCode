import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def provider_config():
    file = ROOT / ".provider_private.json"
    data = json.loads(file.read_text(encoding="utf-8")) if file.exists() else {}
    return {
        "protocol": os.getenv("LLM_PROTOCOL", data.get("protocol", "openai")),
        "base_url": os.getenv("LLM_BASE_URL", data.get("base_url", "https://api.deepseek.com")),
        "model": os.getenv("LLM_MODEL", data.get("model", "deepseek-flash")),
        "api_key": os.getenv("LLM_API_KEY", data.get("api_key", "")),
    }


def scrub(text):
    secret = provider_config()["api_key"]
    if secret:
        text = text.replace(secret, "[REDACTED]")
    return text
