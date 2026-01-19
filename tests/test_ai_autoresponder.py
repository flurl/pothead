
import os
import time
import pytest
import asyncio
import sys
from unittest.mock import AsyncMock, patch, MagicMock, mock_open
from datatypes import ChatMessage, Event, MessageType

# Mock dependencies before importing the plugin
with patch("plugin_manager.get_plugin_settings") as mock_get_plugin_settings:
    mock_plugin_settings_val = MagicMock()
    mock_plugin_settings_val.auto_chat_ids = []
    mock_plugin_settings_val.wait_after_message_from_self = 10
    mock_get_plugin_settings.return_value = mock_plugin_settings_val

    # We need to ensure that the plugin is reloaded for each test if necessary,
    # or at least that its global state is manageable.
    if 'plugins.ai_autoresponder.main' in sys.modules:
        del sys.modules['plugins.ai_autoresponder.main']

    import plugins.ai_autoresponder.main as ai_main

@pytest.fixture(autouse=True)
def reset_auto_chat_ids():
    ai_main.auto_chat_ids.clear()
    ai_main.ignore_time = None
    ai_main.send_to_ai = None


@pytest.mark.asyncio
async def test_cmd_autoenable():
    chat_id = "chat123"
    with patch("plugins.ai_autoresponder.main.save_auto_chat_ids") as mock_save:
        # First enable
        response, attachments = await ai_main.cmd_autoenable(chat_id, [], None)
        assert "enabled" in response
        assert chat_id in ai_main.auto_chat_ids
        mock_save.assert_called_once()

        # Second enable
        mock_save.reset_mock()
        response, attachments = await ai_main.cmd_autoenable(chat_id, [], None)
        assert "already enabled" in response
        mock_save.assert_not_called()


@pytest.mark.asyncio
async def test_cmd_autodisable():
    chat_id = "chat123"
    ai_main.auto_chat_ids.append(chat_id)
    with patch("plugins.ai_autoresponder.main.save_auto_chat_ids") as mock_save:
        # First disable
        response, attachments = await ai_main.cmd_autodisable(chat_id, [], None)
        assert "disabled" in response
        assert chat_id not in ai_main.auto_chat_ids
        mock_save.assert_called_once()

        # Second disable
        mock_save.reset_mock()
        response, attachments = await ai_main.cmd_autodisable(chat_id, [], None)
        assert "not enabled" in response
        mock_save.assert_not_called()


@pytest.mark.asyncio
async def test_on_chat_message_received_not_enabled():
    msg = ChatMessage(source="user1", text="Hello", type=MessageType.CHAT)
    ai_main.send_to_ai = AsyncMock()
    await ai_main.on_chat_message_received(msg)
    ai_main.send_to_ai.assert_not_called()


@pytest.mark.asyncio
async def test_on_chat_message_received_enabled():
    chat_id = "user1"
    ai_main.auto_chat_ids.append(chat_id)
    ai_main.send_to_ai = AsyncMock()
    msg = ChatMessage(source=chat_id, text="Hello", type=MessageType.CHAT, destination=chat_id)

    with patch("plugins.ai_autoresponder.main.settings") as mock_settings:
        mock_settings.trigger_words = ["!pot"]
        mock_settings.signal_account = "bot_account"
        with patch("plugins.ai_autoresponder.main.plugin_settings") as mock_ps:
            mock_ps.wait_after_message_from_self = 10
            await ai_main.on_chat_message_received(msg)
            ai_main.send_to_ai.assert_called_once_with(msg)


@pytest.mark.asyncio
async def test_on_chat_message_received_command_ignored():
    chat_id = "user1"
    ai_main.auto_chat_ids.append(chat_id)
    ai_main.send_to_ai = AsyncMock()
    msg = ChatMessage(source=chat_id, text="!pot#ping", type=MessageType.CHAT, destination=chat_id)

    with patch("plugins.ai_autoresponder.main.settings") as mock_settings:
        mock_settings.trigger_words = ["!pot"]
        mock_settings.signal_account = "bot_account"
        with patch("plugins.ai_autoresponder.main.plugin_settings") as mock_ps:
            mock_ps.wait_after_message_from_self = 10
            await ai_main.on_chat_message_received(msg)
            ai_main.send_to_ai.assert_not_called()


@pytest.mark.asyncio
async def test_on_chat_message_received_from_self():
    chat_id = "user1"
    ai_main.auto_chat_ids.append(chat_id)
    ai_main.send_to_ai = AsyncMock()
    bot_account = "bot_account"
    msg = ChatMessage(source=bot_account, text="Hello", type=MessageType.CHAT, destination=chat_id)

    with patch("plugins.ai_autoresponder.main.settings") as mock_settings:
        mock_settings.trigger_words = ["!pot"]
        mock_settings.signal_account = bot_account

        await ai_main.on_chat_message_received(msg)
        ai_main.send_to_ai.assert_not_called()
        assert ai_main.ignore_time is not None


@pytest.mark.asyncio
async def test_on_chat_message_received_within_wait_time():
    chat_id = "user1"
    ai_main.auto_chat_ids.append(chat_id)
    ai_main.send_to_ai = AsyncMock()
    ai_main.ignore_time = int(time.time())
    msg = ChatMessage(source=chat_id, text="Hello", type=MessageType.CHAT, destination=chat_id)

    with patch("plugins.ai_autoresponder.main.settings") as mock_settings:
        mock_settings.trigger_words = ["!pot"]
        mock_settings.signal_account = "bot_account"
        with patch("plugins.ai_autoresponder.main.plugin_settings") as mock_plugin_settings:
            mock_plugin_settings.wait_after_message_from_self = 10
            await ai_main.on_chat_message_received(msg)
            ai_main.send_to_ai.assert_not_called()


@pytest.mark.asyncio
async def test_on_chat_message_received_after_wait_time():
    chat_id = "user1"
    ai_main.auto_chat_ids.append(chat_id)
    ai_main.send_to_ai = AsyncMock()
    ai_main.ignore_time = int(time.time()) - 20
    msg = ChatMessage(source=chat_id, text="Hello", type=MessageType.CHAT, destination=chat_id)

    with patch("plugins.ai_autoresponder.main.settings") as mock_settings:
        mock_settings.trigger_words = ["!pot"]
        mock_settings.signal_account = "bot_account"
        with patch("plugins.ai_autoresponder.main.plugin_settings") as mock_plugin_settings:
            mock_plugin_settings.wait_after_message_from_self = 10
            await ai_main.on_chat_message_received(msg)
            ai_main.send_to_ai.assert_called_once_with(msg)
            assert ai_main.ignore_time is None


def test_initialize():
    with patch("os.path.exists", return_value=True):
        with patch("builtins.open", mock_open(read_data="chat1\nchat2\n")):
            with patch("plugins.ai_autoresponder.main.get_service", return_value=AsyncMock()) as mock_get_service:
                ai_main.initialize()
                assert "chat1" in ai_main.auto_chat_ids
                assert "chat2" in ai_main.auto_chat_ids
                assert ai_main.send_to_ai is not None
                mock_get_service.assert_called_once_with("send_to_ai")
