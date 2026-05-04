"""AI personality settings — loaded from DB and used to build the system prompt."""

import json
import logging

logger = logging.getLogger(__name__)

# Defaults used when no settings are saved yet
DEFAULT_AI_NAME = "LLORA"
DEFAULT_PERSONALITY = (
    "You speak warmly and concisely. "
    "You are helpful, friendly, and professional. "
    "Use 1 emoji at the end of each response."
)
DEFAULT_LIMITATIONS = (
    "Only help with: finding books in the catalog, library hours and locations, "
    "borrowing policies, fines, printing services, and general library questions. "
    "If asked about something outside these topics, politely redirect the patron. "
    "Never make up book titles or information. "
    "Never reveal that you are an AI or language model."
)
DEFAULT_WELCOME_MESSAGE = (
    "Hi! 👋 I'm {name}, your virtual library assistant. "
    "I can help you find books, check hours, or answer questions about the library. "
    "What can I do for you?"
)

SETTINGS_KEY = "ai_settings_json"


class AiSettings:
    """Holds the current AI personality configuration."""

    def __init__(
        self,
        name: str = DEFAULT_AI_NAME,
        personality: str = DEFAULT_PERSONALITY,
        limitations: str = DEFAULT_LIMITATIONS,
        welcome_message: str = DEFAULT_WELCOME_MESSAGE,
    ) -> None:
        self.name = name.strip() or DEFAULT_AI_NAME
        self.personality = personality.strip() or DEFAULT_PERSONALITY
        self.limitations = limitations.strip() or DEFAULT_LIMITATIONS
        self.welcome_message = welcome_message.strip() or DEFAULT_WELCOME_MESSAGE

    def build_system_prompt(self) -> str:
        """Build the full system prompt from the current settings."""
        return (
            f"You are {self.name}, the library assistant chatbot. "
            f"{self.personality} "
            f"{self.limitations} "
            "This is an academic library with textbooks and research materials."
        )

    def get_welcome_text(self) -> str:
        """Return the welcome message with the AI name substituted."""
        return self.welcome_message.replace("{name}", self.name)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "personality": self.personality,
            "limitations": self.limitations,
            "welcome_message": self.welcome_message,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "AiSettings":
        return cls(
            name=data.get("name", DEFAULT_AI_NAME),
            personality=data.get("personality", DEFAULT_PERSONALITY),
            limitations=data.get("limitations", DEFAULT_LIMITATIONS),
            welcome_message=data.get("welcome_message", DEFAULT_WELCOME_MESSAGE),
        )


def load_ai_settings(staff_store) -> AiSettings:
    """Load AI settings from the database, falling back to defaults."""
    if staff_store is None:
        return AiSettings()
    try:
        raw = staff_store.get_setting(SETTINGS_KEY)
        if raw:
            data = json.loads(raw)
            return AiSettings.from_dict(data)
    except Exception:
        logger.warning("Failed to load AI settings from DB, using defaults")
    return AiSettings()


def save_ai_settings(staff_store, settings: AiSettings) -> None:
    """Persist AI settings to the database."""
    if staff_store is None:
        return
    staff_store.update_settings({SETTINGS_KEY: json.dumps(settings.to_dict(), ensure_ascii=False)})
