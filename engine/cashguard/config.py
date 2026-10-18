from pathlib import Path
from urllib.parse import urlsplit

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CASHGUARD_", env_file=".env", extra="ignore")
    api_key: str = ""
    data_dir: Path = Path("runtime")
    model_url: str = "http://127.0.0.1:8001"
    model_name: str = "Qwen/Qwen3-VL-8B-Instruct"
    max_upload_mb: int = Field(default=150, ge=1, le=1024)
    max_duration_sec: float = Field(default=180, gt=0, le=600)
    deadline_sec: int = Field(default=270, ge=30, le=280)
    retention_hours: int = Field(default=24, ge=1, le=168)
    coarse_frames: int = Field(default=12, ge=4, le=24)
    overview_frames: int = Field(default=16, ge=4, le=80)
    native_video: bool = False
    window_sec: float = Field(default=24, ge=4, le=60)
    stride_sec: float = Field(default=20, gt=0, le=60)
    max_candidates: int = Field(default=20, ge=1, le=20)
    confirmation_threshold: float = Field(default=0.75, ge=0, le=1)
    departure_checks: bool = True
    workflow_context: bool = False
    screen_recheck: bool = True
    storage_detail: bool = True
    identity_checks: bool = True
    disabled_rule_ids: tuple[str, ...] = ("count_without_customer",)


    @model_validator(mode="after")
    def covering_windows(self):
        if self.stride_sec > self.window_sec:
            raise ValueError("Stride must not exceed window length; that would leave unreviewed gaps")
        if not self.native_video and self.overview_frames > 23:
            raise ValueError("More than 23 context frames requires native video encoding")
        return self

    @field_validator("model_url")
    @classmethod
    def local_only(cls, value):
        url = urlsplit(value)
        if url.scheme != "http" or url.hostname not in {"127.0.0.1", "::1"} or url.username or url.password or url.path not in {"", "/"} or url.query or url.fragment:
            raise ValueError("Model server must be a literal loopback HTTP address; cloud endpoints are prohibited.")
        return value.rstrip("/")

