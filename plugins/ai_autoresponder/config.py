from pydantic.fields import Field
from plugin_manager import PluginSettingsBase


class PluginSettings(PluginSettingsBase):
    auto_chat_ids: list[str] = Field(
        default=[], description="A list of chat ids for which autoresponder should respond to incoming messages.")
    wait_after_message_from_self: int = Field(
        default=300, description="How long the plugin ignores further messages after a message from the bot's account was received (in seconds).")
