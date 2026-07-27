from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Callable

from dotenv import load_dotenv


SecretGetter = Callable[[str, str], object]


@dataclass(frozen=True)
class AppConfig:
    serpapi_api_key: str
    openai_api_key: str
    openai_model: str
    country_code: str
    language: str
    app_password: str
    allow_user_api_keys: bool
    allow_public_with_server_keys: bool
    default_location: str
    max_upload_mb: int
    max_inputs: int
    max_search_jobs: int


def _as_bool(value: object, default: bool = False) -> bool:
    if value is None:
        return default
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return default


def _as_int(value: object, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(parsed, maximum))


def _clean_secret(value: object) -> str:
    text = str(value or "").strip()
    lowered = text.lower()
    placeholder_prefixes = (
        "put_your_",
        "paste_your_",
        "paste-your-",
        "choose_a_",
        "choose-a-",
    )
    if lowered.startswith(placeholder_prefixes) or lowered in {"changeme", "change_me", "replace_me"}:
        return ""
    return text


def load_config(secret_getter: SecretGetter | None = None) -> AppConfig:
    """Load local and hosted configuration.

    Local development can use a .env file. Streamlit Community Cloud can pass
    ``st.secrets.get`` as ``secret_getter``. Render and other hosts can use
    environment variables. Environment variables take precedence.
    """
    load_dotenv()

    def get(name: str, default: str = "") -> str:
        env_value = os.getenv(name)
        if env_value is not None:
            return str(env_value).strip()
        if secret_getter is not None:
            try:
                value = secret_getter(name, default)
            except Exception:  # pragma: no cover - defensive around host secret stores.
                value = default
            return str(value).strip() if value is not None else default
        return default

    return AppConfig(
        serpapi_api_key=_clean_secret(get("SERPAPI_API_KEY")),
        openai_api_key=_clean_secret(get("OPENAI_API_KEY")),
        openai_model=get("OPENAI_MODEL", "gpt-4.1-mini") or "gpt-4.1-mini",
        country_code=(get("COUNTRY_CODE", "us") or "us").lower(),
        language=(get("LANGUAGE", "en") or "en").lower(),
        app_password=_clean_secret(get("APP_PASSWORD")),
        allow_user_api_keys=_as_bool(get("ALLOW_USER_API_KEYS", "false"), False),
        allow_public_with_server_keys=_as_bool(get("ALLOW_PUBLIC_WITH_SERVER_KEYS", "false"), False),
        default_location=get("DEFAULT_LOCATION", "Los Angeles, CA") or "Los Angeles, CA",
        max_upload_mb=_as_int(get("MAX_UPLOAD_MB", "10"), 10, 1, 25),
        max_inputs=_as_int(get("MAX_INPUTS", "12"), 12, 1, 30),
        max_search_jobs=_as_int(get("MAX_SEARCH_JOBS", "24"), 24, 1, 60),
    )
