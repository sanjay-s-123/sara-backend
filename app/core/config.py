from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional


class Settings(BaseSettings):
    ENVIRONMENT: str = "development"
    PORT: int = 8000
    HOST: str = "0.0.0.0"
    ALLOWED_ORIGINS: str = "*"

    # Firebase
    FIREBASE_PROJECT_ID: str = "sara-mobile-b09fe"
    FIREBASE_CREDENTIALS_PATH: Optional[str] = "./service-account.json"
    FIREBASE_AUTH_EMULATOR_HOST: Optional[str] = None
    FIRESTORE_EMULATOR_HOST: Optional[str] = None

    # AI Provider
    LLM_PROVIDER: str = "gemini"
    LLM_API_KEY: Optional[str] = None
    LLM_MODEL: Optional[str] = "gemini-flash-lite-latest"

    # Sarvam AI Voice TTS
    SARVAM_API_KEY: Optional[str] = None
    SARVAM_TTS_MODEL: str = "bulbul:v1"
    SARVAM_DEFAULT_SPEAKER: str = "meera"
    SARVAM_DEFAULT_LANGUAGE: str = "en-IN"

    # Telephony / Voice Calling
    TELEPHONY_PROVIDER: str = "auto"  # 'twilio', 'mock', 'device_direct'
    TWILIO_ACCOUNT_SID: Optional[str] = None
    TWILIO_AUTH_TOKEN: Optional[str] = None
    TWILIO_FROM_NUMBER: Optional[str] = None
    VOICE_CALL_WEBHOOK_BASE_URL: Optional[str] = None
    VOICE_CALL_DEFAULT_LEAD_MINUTES: int = 5
    VOICE_CALL_MAX_RETRIES: int = 2

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
