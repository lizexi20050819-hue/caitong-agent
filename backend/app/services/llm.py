"""LLM config loader — supports DeepSeek and OpenAI-compatible APIs."""

import os
from dotenv import load_dotenv

load_dotenv()


def load_config() -> dict[str, str] | None:
    """Load LLM API config from environment."""
    provider = os.getenv("LLM_PROVIDER", "deepseek").lower()

    if provider == "deepseek":
        key = os.getenv("DEEPSEEK_API_KEY")
        if not key:
            return None
        return {
            "api_key": key,
            "model": os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
            "base_url": os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
        }

    key = os.getenv("OPENAI_API_KEY")
    if not key:
        return None
    return {
        "api_key": key,
        "model": os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        "base_url": os.getenv("OPENAI_BASE_URL"),
    }
