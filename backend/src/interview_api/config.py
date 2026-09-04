from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables and `.env`."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "AI Interview Backend"
    app_env: Literal["local", "test", "production"] = "local"

    openai_api_key: SecretStr | None = None
    openai_proxy_url: SecretStr | None = None
    openrouter_model: str = "openai/gpt-5.6-luna"
    openrouter_fallback_model: str | None = "deepseek/deepseek-v4-flash-0731"
    openrouter_timeout_seconds: float = Field(default=90.0, gt=0, le=600)
    openrouter_max_retries: int = Field(default=1, ge=0, le=5)
    question_generation_model: str = "openai/gpt-5.6-luna"
    interview_judge_workers: int = Field(default=6, ge=1, le=20)

    question_prompt_path: Path = Path("app/prompts/initial_questions_v1.txt")
    max_document_bytes: int = Field(default=10 * 1024 * 1024, gt=0)
    max_document_characters: int = Field(default=100_000, gt=0)
    max_audio_bytes: int = Field(default=20 * 1024 * 1024, gt=0)
    whisper_model_size: str = "small"
    whisper_device: str = "cpu"
    whisper_compute_type: str = "int8"
    whisper_timeout_seconds: float = Field(default=300.0, gt=0, le=1800)
    whisper_beam_size: int = Field(default=5, ge=1, le=20)


@lru_cache
def get_settings() -> Settings:
    return Settings()
