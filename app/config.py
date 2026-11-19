import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    mysql_host: str = os.getenv("MYSQL_HOST", "127.0.0.1")
    mysql_port: int = int(os.getenv("MYSQL_PORT", "3306"))
    mysql_user: str = os.getenv("MYSQL_USER", "root")
    mysql_password: str = os.getenv("MYSQL_PASSWORD", "")
    mysql_database: str = os.getenv("MYSQL_DATABASE", "paper_assistant")
    chat_api_key: str = os.getenv("DEEPSEEK_API_KEY", "")
    chat_base_url: str = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    chat_model: str = os.getenv("DEEPSEEK_MODEL", "deepseek-flash")
    serpapi_key: str = os.getenv("SERPAPI_API_KEY", "")
    openalex_api_key: str = os.getenv("OPENALEX_API_KEY", "")
    max_upload_mb: int = int(os.getenv("MAX_UPLOAD_MB", "10"))
    reading_context_tokens: int = int(os.getenv("READING_CONTEXT_TOKENS", "32000"))


settings = Settings()
