from pydantic.fields import Field
from plugin_manager import PluginSettingsBase


class PluginSettings(PluginSettingsBase):
    # sensitive info, either set in config.toml or via env variable
    gemini_api_key: str

    system_instruction: str = "You are a helpful assistant."
    gemini_model_name: str = "gemini-2.5-flash"
    context_expiry_threshold: int = Field(
        default=300, description="After how many seconds without a message a new chat context should be started.")
