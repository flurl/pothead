from plugin_manager import PluginSettingsBase


class PluginSettings(PluginSettingsBase):
    max_messages_per_file: int = 100
