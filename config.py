import os
from pydantic import Field
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict, TomlConfigSettingsSource


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file_encoding="utf-8",
        env_file=".env",
        env_prefix="POTHEAD_",
        case_sensitive=False,
        toml_file="pothead.toml",
        extra="ignore",
    )

    # Sensitive settings from environment variables
    signal_account: str
    superuser: str

    # Settings from pothead.toml with environment variable overrides
    signal_cli_path: str = "signal-cli/signal-cli"
    signal_attachments_path: str = os.path.expanduser(
        "~/.local/share/signal-cli/attachments"
    )
    permissions_store_path: str = "permissions"
    trigger_words: list[str] = ["!pot", "!pothead", "!ph"]
    file_store_path: str = "document_store"
    history_max_length: int = 30
    log_level: str = "INFO"
    enabled_plugins: list[str] = []
    settle_time: int = Field(
        default=30, description="Seconds to wait until processing of incoming messages starts")
    message_prefix: str = Field(
        default="", description="Prefix to prepend to all messages sent by the bot")

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return (
            init_settings,
            env_settings,
            dotenv_settings,
            TomlConfigSettingsSource(settings_cls),
            file_secret_settings,
        )


settings = Settings()  # type: ignore
