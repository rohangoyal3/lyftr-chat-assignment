import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv


DEFAULT_MODEL = "gemini/gemini-3.5-flash-lite"
DEFAULT_PROMPT = "You are Lyftr, a helpful assistant. Give clear, accurate answers."
DEFAULT_ORIGINS = "http://localhost:3000,http://127.0.0.1:3000"


@dataclass(frozen=True)
class Settings:
    api_keys: tuple[str, ...] = field(repr=False)
    db_path: Path
    model: str = DEFAULT_MODEL
    allowed_origins: tuple[str, ...] = tuple(DEFAULT_ORIGINS.split(","))
    enable_failure_simulation: bool = False
    default_system_prompt: str = DEFAULT_PROMPT
    timeout_seconds: float = 20.0
    cache_ttl_seconds: int = 3600
    api_base: str | None = None

    def __post_init__(self) -> None:
        if len(self.api_keys) < 2 or len(set(self.api_keys)) != len(self.api_keys):
            raise ValueError("LLM_API_KEYS must contain at least two distinct keys")
        if any(not key or key.startswith("replace-me-") for key in self.api_keys):
            raise ValueError("LLM_API_KEYS must contain real provider keys")
        if not self.model or self.timeout_seconds <= 0 or self.cache_ttl_seconds <= 0:
            raise ValueError("Set a model and positive timeout and cache TTL values")

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv(Path(__file__).resolve().parents[2] / ".env")
        database_url = os.getenv("DATABASE_URL", "sqlite:///./data/app.db")
        prefix = "sqlite:///"
        if not database_url.startswith(prefix) or database_url[len(prefix):] in {"", ":memory:"}:
            raise ValueError("DATABASE_URL must point to a SQLite file using sqlite:///path")

        return cls(
            api_keys=tuple(key.strip() for key in os.getenv("LLM_API_KEYS", "").split(",")),
            db_path=Path(database_url[len(prefix):]),
            model=os.getenv("LLM_MODEL", DEFAULT_MODEL).strip(),
            allowed_origins=tuple(
                origin.strip().rstrip("/")
                for origin in os.getenv("ALLOWED_ORIGINS", DEFAULT_ORIGINS).split(",")
                if origin.strip()
            ),
            enable_failure_simulation=os.getenv("ENABLE_FAILURE_SIMULATION", "false").strip().lower() == "true",
            default_system_prompt=os.getenv("DEFAULT_SYSTEM_PROMPT", DEFAULT_PROMPT),
            timeout_seconds=float(os.getenv("LLM_TIMEOUT_SECONDS", "20")),
            cache_ttl_seconds=int(os.getenv("CACHE_TTL_SECONDS", "3600")),
            api_base=os.getenv("LLM_API_BASE") or None,
        )
