from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    openai_api_key: str = "sk-placeholder"
    openai_base_url: str = "https://api.agentplatform.ru/v1"
    openai_model: str = "openai/gpt-5-mini"

    kafka_bootstrap_servers: str = "localhost:9092"
    kafka_topic_emails: str = "email-extraction-tasks"
    kafka_consumer_group: str = "email-extraction-workers"

    webhook_url: str = ""
    test_webhook_url: str = ""

    max_retries: int = 3

    log_level: str = "INFO"

    host: str = "0.0.0.0"
    port: int = 8000

    upload_dir: str = "./uploads"
    upload_cleanup_hours: int = 24


settings = Settings()
