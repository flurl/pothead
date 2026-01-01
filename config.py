import os
from typing import List, Tuple
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict, TomlConfigSettingsSource


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file_encoding="utf-8",
        env_prefix="POTHEAD_",
        case_sensitive=False,
        toml_file="pothead.toml",
    )

    # Sensitive settings from environment variables
    signal_account: str
    target_sender: str
    gemini_api_key: str

    # Settings from pothead.toml with environment variable overrides
    signal_cli_path: str = "signal-cli/signal-cli"
    signal_attachments_path: str = os.path.expanduser(
        "~/.local/share/signal-cli/attachments"
    )
    gemini_model_name: str = "gemini-2.5-flash"
    trigger_words: List[str] = ["!pot", "!pothead", "!ph"]
    file_store_path: str = "document_store"
    history_max_length: int = 30
    log_level: str = "INFO"
    system_instruction: str = "You are a helpful assistant."

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> Tuple[PydanticBaseSettingsSource, ...]:
        return (
            init_settings,
            env_settings,
            dotenv_settings,
            TomlConfigSettingsSource(settings_cls),
            file_secret_settings,
        )


settings = Settings()  # type: ignore
