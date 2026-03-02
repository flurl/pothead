
import pytest
import json
import os
import dataclasses
from unittest.mock import AsyncMock, MagicMock, patch, mock_open
from datatypes import ChatMessage, EditMessage, DeleteMessage, MessageType, Attachment
from plugins.archiver.main import (
    load_enabled_chats,
    save_enabled_chats,
    cmd_enable_archive,
    cmd_disable_archive,
    on_chat_event,
    ENABLED_CHATS_FILE,
    ARCHIVES_DIR
)
import plugins.archiver.main as archiver_main

@pytest.fixture(autouse=True)
def clear_enabled_chats():
    archiver_main.enabled_chats.clear()
    yield
    archiver_main.enabled_chats.clear()

def test_load_enabled_chats_file_exists():
    mock_data = ["chat1", "chat2"]
    with patch("os.path.exists", return_value=True):
        with patch("builtins.open", mock_open(read_data=json.dumps(mock_data))):
            chats = load_enabled_chats()
            assert chats == {"chat1", "chat2"}

def test_load_enabled_chats_file_not_exists():
    with patch("os.path.exists", return_value=False):
        chats = load_enabled_chats()
        assert chats == set()

def test_load_enabled_chats_error():
    with patch("os.path.exists", return_value=True):
        with patch("builtins.open", side_effect=Exception("Read error")):
            chats = load_enabled_chats()
            assert chats == set()

def test_save_enabled_chats():
    chats = {"chat1", "chat2"}
    m = mock_open()
    with patch("builtins.open", m):
        save_enabled_chats(chats)
        m.assert_called_once_with(ENABLED_CHATS_FILE, "w")
        handle = m()
        # json.dump called, check what was written
        # Since it's a set, order might vary, so we parse it back
        written_data = "".join(call.args[0] for call in handle.write.call_args_list)
        assert set(json.loads(written_data)) == chats

@pytest.mark.asyncio
async def test_cmd_enable_archive():
    chat_id = "chat123"
    with patch("plugins.archiver.main.save_enabled_chats") as mock_save:
        response, _ = await cmd_enable_archive(chat_id, [], None)
        assert "enabled" in response
        assert chat_id in archiver_main.enabled_chats
        mock_save.assert_called_once()

    # Enable again
    with patch("plugins.archiver.main.save_enabled_chats") as mock_save:
        response, _ = await cmd_enable_archive(chat_id, [], None)
        assert "already enabled" in response
        mock_save.assert_not_called()

@pytest.mark.asyncio
async def test_cmd_disable_archive():
    chat_id = "chat123"
    archiver_main.enabled_chats.add(chat_id)

    with patch("plugins.archiver.main.save_enabled_chats") as mock_save:
        response, _ = await cmd_disable_archive(chat_id, [], None)
        assert "disabled" in response
        assert chat_id not in archiver_main.enabled_chats
        mock_save.assert_called_once()

    # Disable again
    with patch("plugins.archiver.main.save_enabled_chats") as mock_save:
        response, _ = await cmd_disable_archive(chat_id, [], None)
        assert "was not enabled" in response
        mock_save.assert_not_called()

@pytest.mark.asyncio
async def test_on_chat_event_not_enabled():
    msg = ChatMessage(source="+123", destination="chat123", type=MessageType.CHAT, text="Hello")
    with patch("os.makedirs") as mock_makedirs:
        await on_chat_event(msg)
        mock_makedirs.assert_not_called()

@pytest.mark.asyncio
async def test_on_chat_event_chat_message():
    chat_id = "chat123"
    archiver_main.enabled_chats.add(chat_id)
    msg = ChatMessage(source="+123", destination=chat_id, type=MessageType.CHAT, text="Hello", timestamp=1000)

    with patch("plugins.archiver.main.get_safe_chat_dir", return_value="/tmp/chat123") as mock_get_dir, \
         patch("os.makedirs") as mock_makedirs, \
         patch("builtins.open", mock_open()) as mock_file:

        await on_chat_event(msg)

        mock_get_dir.assert_called_once_with(ARCHIVES_DIR, chat_id)
        mock_makedirs.assert_called_with("/tmp/chat123", exist_ok=True)
        mock_file.assert_called_with(os.path.join("/tmp/chat123", "messages.jsonl"), "a", encoding="utf-8")

        handle = mock_file()
        written_line = handle.write.call_args[0][0]
        data = json.loads(written_line)
        assert data["text"] == "Hello"
        assert data["type"] == "chat"

@pytest.mark.asyncio
async def test_on_chat_event_edit_message():
    chat_id = "chat123"
    archiver_main.enabled_chats.add(chat_id)
    msg = EditMessage(source="+123", destination=chat_id, type=MessageType.EDIT, text="Edited", timestamp=2000, target_sent_timestamp=1000)

    with patch("plugins.archiver.main.get_safe_chat_dir", return_value="/tmp/chat123"), \
         patch("os.makedirs"), \
         patch("builtins.open", mock_open()) as mock_file:

        await on_chat_event(msg)

        handle = mock_file()
        written_line = handle.write.call_args[0][0]
        data = json.loads(written_line)
        assert data["text"] == "Edited"
        assert data["type"] == "edit"
        assert data["target_sent_timestamp"] == 1000

@pytest.mark.asyncio
async def test_on_chat_event_delete_message():
    chat_id = "chat123"
    archiver_main.enabled_chats.add(chat_id)
    msg = DeleteMessage(source="+123", destination=chat_id, type=MessageType.DELETE, timestamp=3000, target_sent_timestamp=1000)

    with patch("plugins.archiver.main.get_safe_chat_dir", return_value="/tmp/chat123"), \
         patch("os.makedirs"), \
         patch("builtins.open", mock_open()) as mock_file:

        await on_chat_event(msg)

        handle = mock_file()
        written_line = handle.write.call_args[0][0]
        data = json.loads(written_line)
        assert data["type"] == "delete"
        assert data["target_sent_timestamp"] == 1000

@pytest.mark.asyncio
async def test_on_chat_event_with_attachments():
    chat_id = "chat123"
    archiver_main.enabled_chats.add(chat_id)
    att = Attachment(content_type="image/png", id="att1", size=100, filename="test.png")
    msg = ChatMessage(source="+123", destination=chat_id, type=MessageType.CHAT, text="Image", timestamp=1000, attachments=[att])

    with patch("plugins.archiver.main.get_safe_chat_dir", return_value="/tmp/chat123"), \
         patch("os.makedirs") as mock_makedirs, \
         patch("builtins.open", mock_open()), \
         patch("plugins.archiver.main.save_attachment") as mock_save_att:

        await on_chat_event(msg)

        # Check that attachments dir was created
        mock_makedirs.assert_any_call(os.path.join("/tmp/chat123", "attachments"), exist_ok=True)

        # Check that save_attachment was called
        mock_save_att.assert_called_once()
        call_args = mock_save_att.call_args[0]
        assert call_args[0] == att
        assert call_args[1] == os.path.join("/tmp/chat123", "attachments")
        assert call_args[2] == "1000_att1_test.png"

@pytest.mark.asyncio
async def test_on_chat_event_error_handling():
    chat_id = "chat123"
    archiver_main.enabled_chats.add(chat_id)
    msg = ChatMessage(source="+123", destination=chat_id, type=MessageType.CHAT, text="Hello")

    with patch("plugins.archiver.main.get_safe_chat_dir", side_effect=Exception("Generic error")), \
         patch("plugins.archiver.main.logger") as mock_logger:

        await on_chat_event(msg)
        mock_logger.error.assert_called_once()
        assert "Error archiving message" in mock_logger.error.call_args[0][0]
