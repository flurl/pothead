from typing import cast
import unittest
from unittest.mock import patch, MagicMock
from plugin_manager import get_plugin_settings
from plugins.echo.config import PluginSettings


class TestPluginManager(unittest.TestCase):
    def test_get_plugin_settings(self):
        """
        Tests that get_plugin_settings correctly loads a plugin's configuration.
        """
        from plugins.echo.config import PluginSettings
        # Patch the logger to avoid polluting test output
        with patch("plugin_manager.logger"):
            settings: PluginSettings = cast(
                PluginSettings, get_plugin_settings("echo"))
            self.assertIsNotNone(settings)
            self.assertEqual(settings.echo_prefix, "Echo (from toml):")


if __name__ == "__main__":
    unittest.main()
