import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[3]


@dataclass(frozen=True)
class Settings:
    db_path: Path
    llm_base_url: str = "https://api.openai.com/v1"
    llm_api_key: str = ""
    llm_model: str = ""
    llm_timeout: float = 90
    llm_max_output_tokens: int = 6000
    stt_model: str = "elevenlabs/scribe-v2"
    decision_model: str = "typesafe/jev-1.14"
    environment: str = "development"
    password_hash: str = ""
    allowed_origins: tuple[str, ...] = (
        "http://127.0.0.1:5173",
        "http://localhost:5173",
        "http://127.0.0.1:8000",
        "http://localhost:8000",
    )
    frontend_dir: Path | None = None
    session_hours: int = 8
    paid_per_hour: int = 60

    def validate_security(self):
        if self.environment not in ("development", "production"):
            raise ValueError("CQA_ENV must be development or production")
        if not self.allowed_origins or any(
            not urlparse(o).hostname
            or urlparse(o).path
            or urlparse(o).query
            or urlparse(o).fragment
            or urlparse(o).username
            or "*" in o
            or urlparse(o).scheme not in ("http", "https")
            for o in self.allowed_origins
        ):
            raise ValueError("CQA_ALLOWED_ORIGINS must contain exact origins without paths")
        if self.environment == "production":
            if not self.password_hash:
                raise ValueError("Configure the administrator password before production startup")
            if any(urlparse(o).scheme != "https" for o in self.allowed_origins):
                raise ValueError("Production requires HTTPS origins")
        if not 1 <= self.session_hours <= 24 or not 1 <= self.paid_per_hour <= 1000:
            raise ValueError("Session and processing limits are outside the supported range")

    audio_hosts: tuple[str, ...] = (
        "ec88f21f1accecf38e20095a9fe175.a5.environment.api.powerplatform.com",
        "freedomholdingcorporation.crm11.dynamics.com",
    )

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv(ROOT / ".env")
        path = Path(os.getenv("CQA_DB_PATH", "data/cqa.sqlite3"))
        return cls(
            db_path=path if path.is_absolute() else ROOT / path,
            llm_base_url=os.getenv("LLM_BASE_URL", "https://api.openai.com/v1").strip(),
            llm_api_key=os.getenv("LLM_API_KEY", "").strip(),
            llm_model=os.getenv("LLM_MODEL", "").strip(),
            llm_timeout=float(os.getenv("LLM_TIMEOUT_SECONDS", "90")),
            llm_max_output_tokens=int(os.getenv("LLM_MAX_OUTPUT_TOKENS", "6000")),
            stt_model=os.getenv("STT_MODEL", "elevenlabs/scribe-v2"),
            decision_model=os.getenv("DECISION_MODEL", "typesafe/jev-1.14"),
            environment=os.getenv("CQA_ENV", "development"),
            password_hash=os.getenv("CQA_PASSWORD_HASH", ""),
            allowed_origins=tuple(
                o.strip().rstrip("/")
                for o in os.getenv(
                    "CQA_ALLOWED_ORIGINS",
                    "http://127.0.0.1:5173,http://localhost:5173,http://127.0.0.1:8000,http://localhost:8000",
                ).split(",")
                if o.strip()
            ),
            frontend_dir=Path(os.environ["CQA_FRONTEND_DIR"])
            if os.getenv("CQA_FRONTEND_DIR")
            else None,
            session_hours=int(os.getenv("CQA_SESSION_HOURS", "8")),
            paid_per_hour=int(os.getenv("CQA_PAID_PER_HOUR", "60")),
        )
