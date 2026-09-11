"""Configuration management for Tandem."""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration loaded from environment or .env file."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    tandem_env: str = "development"
    tandem_host: str = "127.0.0.1"
    tandem_port: int = 8000

    # Simulator ports
    core_bank_port: int = 8001
    core_bank_2_port: int = 8002
    processor_port: int = 8003
    documents_port: int = 8004

    # Persistence
    tandem_db_path: str = "tandem_ledger.db"

    # Playwright
    playwright_headless: bool = True

    # LLM keys for discovery (optional fallback available)
    openai_api_key: str = ""
    anthropic_api_key: str = ""

    # Base URLs
    @property
    def core_bank_url(self) -> str:
        return f"http://{self.tandem_host}:{self.core_bank_port}"

    @property
    def core_bank_2_url(self) -> str:
        return f"http://{self.tandem_host}:{self.core_bank_2_port}"

    @property
    def processor_url(self) -> str:
        return f"http://{self.tandem_host}:{self.processor_port}"

    @property
    def documents_url(self) -> str:
        return f"http://{self.tandem_host}:{self.documents_port}"

    @property
    def tandem_api_url(self) -> str:
        return f"http://{self.tandem_host}:{self.tandem_port}"


# Singleton instance
settings = Settings()
