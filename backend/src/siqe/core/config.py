"""Application settings, read from environment variables prefixed with ``SIQE_``.

Every setting is documented in ``.env.example`` at the repository root.
"""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from siqe import __version__

CPU_TASK_QUEUE = "siqe-cpu"
GPU_TASK_QUEUE = "siqe-gpu"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SIQE_", env_file=".env", extra="ignore")

    # Identity
    version: str = Field(default=__version__, description="Set from the git tag at image build time.")
    environment: Literal["development", "production", "test"] = "production"

    # Logging
    log_level: str = "INFO"
    log_json: bool = True

    # Storage and services
    data_dir: Path = Path("/data")
    database_url: str = "postgresql+asyncpg://siqe:siqe@db:5432/siqe"
    temporal_address: str = "temporal:7233"
    temporal_namespace: str = "siqe"
    temporal_retention_days: int = 7

    # Workers
    cpu_concurrency: int = Field(default=0, description="Concurrent CPU activities; 0 means one per core.")
    worker_heartbeat_seconds: float = 10.0

    # Resource limits (see docs/robustness.md)
    max_input_megapixels: int = 250
    max_upload_mb: int = Field(default=2048, description="Largest single upload, in MB.")
    max_output_megapixels: int = Field(
        default=1000, description="Largest AI result, in megapixels (8K ×4 is 531 MP)."
    )
    gpu_vram_reserve_mb: int = Field(
        default=1536, description="VRAM kept free for the driver and fragmentation."
    )
    min_free_disk_ratio: float = 0.05

    # Library import folder (mounted read-only from the host; see SIQE_IMPORT_PATH in .env)
    import_dir: Path = Field(default=Path("/import"), description="Import folder inside the containers.")
    import_host_path: str = Field(
        default="./import", description="The same folder on your computer, shown in the Library."
    )
    import_scan_seconds: int = Field(
        default=60, description="How often the import folder is checked for new images; 0 turns it off."
    )
    import_settle_seconds: int = Field(
        default=15, description="A file must be unchanged this long before it is imported."
    )

    # Flows
    output_dir: Path = Field(
        default=Path("/output"), description="Where flows export files, in the containers."
    )
    output_host_path: str = Field(default="./output", description="The same folder on your computer.")
    flow_concurrency: int = Field(default=4, description="Images a flow run works on at the same time.")

    # Access
    api_auth: Literal["off", "keys"] = Field(
        default="off",
        description="'keys': every client, the web app included, needs an API key. 'off': trust the network.",
    )

    # Updates (GitHub releases)
    update_repo: str = "AmerZuher/Super-Image-Quality-Enhancer"
    update_check_hours: float = 6.0
    update_include_prereleases: bool = False
    github_token: SecretStr | None = None

    @property
    def sync_database_dsn(self) -> str:
        """Plain ``postgresql://`` DSN for asyncpg's LISTEN connection."""
        return self.database_url.replace("postgresql+asyncpg://", "postgresql://", 1)


@lru_cache
def get_settings() -> Settings:
    return Settings()
