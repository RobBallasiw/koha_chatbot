"""Configuration module — loads settings from environment variables."""

import sys
from dataclasses import dataclass

from dotenv import load_dotenv
import os

# Load .env file if present (no error if missing)
load_dotenv()

REQUIRED_ENV_VARS = [
    "KOHA_API_URL",
    "GROQ_API_KEY",
    "GROQ_API_URL",
    "LIBRARY_INFO_PATH",
]


@dataclass
class Settings:
    """Application settings loaded from environment variables."""

    koha_api_url: str
    groq_api_key: str
    groq_api_url: str
    library_info_path: str


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
        groq_api_key=os.environ["GROQ_API_KEY"],
        groq_api_url=os.environ["GROQ_API_URL"],
        library_info_path=os.environ["LIBRARY_INFO_PATH"],
    )
