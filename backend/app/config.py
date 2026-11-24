"""
Application configuration using pydantic-settings.
All values are read from environment variables or the .env file.
No secrets are hardcoded here.
"""

from pathlib import Path
from typing import List
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import AliasChoices, Field, field_validator


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Application ───────────────────────────────────────────────────────────
    app_title: str = "AI Plot Layout Management"
    app_version: str = "1.0.0"
    debug: bool = False

    # ── Server ────────────────────────────────────────────────────────────────
    host: str = "0.0.0.0"
    port: int = 8000

    # ── Database ──────────────────────────────────────────────────────────────
    database_url: str = "sqlite+aiosqlite:///./plotlayout.db"

    # ── File Storage ──────────────────────────────────────────────────────────
    upload_dir: Path = Path("uploads")
    output_dir: Path = Path("outputs")
    max_file_size_mb: int = 50
    allowed_extensions: List[str] = ["png", "jpg", "jpeg", "webp"]

    # ── OpenRouter Vision LLM ─────────────────────────────────────────────────
    openrouter_api_key: str = ""
    openrouter_vision_model: str = Field(
        default="openrouter/free",
        validation_alias=AliasChoices("VISION_MODEL", "OPENROUTER_VISION_MODEL"),
    )
    openrouter_base_url: str = "https://openrouter.ai/api/v1"

    # ── Google Gemini (free OCR boost) ────────────────────────────────────────
    gemini_api_key: str = ""
    gemini_ocr_model: str = "gemini-2.0-flash"   # free tier: 1500 req/day
    enable_gemini_ocr: bool = False               # set to true in .env to activate

    # ── Groq Vision (free OCR boost alternative) ──────────────────────────────
    groq_api_key: str = ""
    enable_groq_ocr: bool = False                 # set to true in .env to activate

    # ── Pipeline Feature Flags ────────────────────────────────────────────────
    enable_ocr: bool = True
    enable_llm: bool = True
    enable_yolo: bool = Field(
        default=False,
        validation_alias=AliasChoices("YOLO_ENABLED", "ENABLE_YOLO"),
    )  # Off by default until a survey-specific model exists

    # ── Model Paths ───────────────────────────────────────────────────────────
    yolo_model: str = Field(
        default="",
        validation_alias=AliasChoices("YOLO_MODEL_PATH", "YOLO_MODEL"),
    )
    yolo_allowed_classes: str = ""
    ocr_language: str = "en"

    # ── CORS (stored as comma-separated string in .env) ───────────────────────
    # pydantic-settings v2 requires JSON array format for List fields in .env.
    # We use a string field + property to allow simple comma-separated values.
    cors_origins: str = "http://localhost:5173,http://localhost:3000"

    # ── Confidence Thresholds ─────────────────────────────────────────────────
    min_geometry_confidence: float = 0.72
    min_ocr_confidence: float = 0.60

    # ── Derived Properties ────────────────────────────────────────────────────
    @property
    def cors_origin_list(self) -> List[str]:
        """Parse comma-separated CORS origins."""
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def max_file_size_bytes(self) -> int:
        return self.max_file_size_mb * 1024 * 1024

    def resolve_storage_dir(self, path: Path) -> Path:
        """Resolve relative upload/output paths from the backend directory, not process CWD."""
        if path.is_absolute():
            return path
        backend_root = Path(__file__).resolve().parents[1]
        return (backend_root / path).resolve()

    @property
    def resolved_upload_dir(self) -> Path:
        return self.resolve_storage_dir(self.upload_dir)

    @property
    def resolved_output_dir(self) -> Path:
        return self.resolve_storage_dir(self.output_dir)

    @property
    def has_openrouter_key(self) -> bool:
        return bool(
            self.openrouter_api_key
            and self.openrouter_api_key != "your_openrouter_api_key_here"
        )

    @property
    def yolo_is_configured(self) -> bool:
        """A usable detector needs local weights and explicit survey classes."""
        return bool(
            self.yolo_model
            and Path(self.yolo_model).expanduser().is_file()
            and any(name.strip() for name in self.yolo_allowed_classes.split(","))
        )

    @field_validator("upload_dir", "output_dir", mode="before")
    @classmethod
    def parse_path(cls, v) -> Path:
        return Path(v)

    @field_validator("allowed_extensions", mode="before")
    @classmethod
    def parse_extensions(cls, v):
        """Accept comma-separated strings or JSON lists."""
        if isinstance(v, list):
            return v
        if isinstance(v, str):
            v = v.strip().strip("[]")
            return [item.strip().strip("\"'") for item in v.split(",") if item.strip()]
        return v


# Singleton settings instance — import this everywhere
settings = Settings()
