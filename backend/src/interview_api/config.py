from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
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

    ollama_host: str = "http://127.0.0.1:11434"
    ollama_question_model: str = "qwen3:4b"
    ollama_timeout_seconds: float = Field(default=120.0, gt=0, le=600)
    ollama_context_length: int = Field(default=16_384, ge=4096, le=262_144)

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
