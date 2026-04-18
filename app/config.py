"""Configuration module — loads settings from environment variables."""

import sys
from dataclasses import dataclass

from dotenv import load_dotenv
import os

# Load .env file if present (no error if missing)
load_dotenv()

REQUIRED_ENV_VARS = [
    "KOHA_API_URL",
    "LIBRARY_INFO_PATH",
]


@dataclass
class Settings:
    """Application settings loaded from environment variables."""

    koha_api_url: str
    library_info_path: str
    ollama_url: str = "http://localhost:11434/v1"
    ollama_model: str = "llama3.2:3b"
    admin_api_key: str | None = None
    messenger_link: str = "https://m.me/your-library-page"
    smtp_email: str | None = None
    smtp_password: str | None = None
    librarian_email: str | None = None
    chatbot_public_url: str = "http://localhost:8000"
    ntfy_topic: str | None = None


def load_settings() -> Settings:
    """Load and validate settings from environment variables.

    Raises SystemExit with a descriptive error naming the missing variable
    if any required environment variable is absent.
    """
    missing = [var for var in REQUIRED_ENV_VARS if not os.environ.get(var)]
    if missing:
        for var in missing:
            print(f"Error: Required environment variable '{var}' is not set.", file=sys.stderr)
        sys.exit(1)

    return Settings(
        koha_api_url=os.environ["KOHA_API_URL"],
        library_info_path=os.environ["LIBRARY_INFO_PATH"],
        ollama_url=os.environ.get("OLLAMA_URL", "http://localhost:11434/v1"),
        ollama_model=os.environ.get("OLLAMA_MODEL", "llama3.2:3b"),
        admin_api_key=os.environ.get("ADMIN_API_KEY"),
        messenger_link=os.environ.get("MESSENGER_LINK", "https://m.me/your-library-page"),
        smtp_email=os.environ.get("SMTP_EMAIL"),
        smtp_password=os.environ.get("SMTP_PASSWORD"),
        librarian_email=os.environ.get("LIBRARIAN_EMAIL"),
        chatbot_public_url=os.environ.get("CHATBOT_PUBLIC_URL", "http://localhost:8000"),
        ntfy_topic=os.environ.get("NTFY_TOPIC"),
    )
