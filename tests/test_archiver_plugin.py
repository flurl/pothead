
import pytest
import json
import os
import dataclasses
from unittest.mock import AsyncMock, MagicMock, call, patch, mock_open
from datatypes import ChatMessage, EditMessage, DeleteMessage, MessageType, Attachment
from plugins.archiver.main import (
    load_enabled_chats,
    save_enabled_chats,
    cmd_enable_archive,
    cmd_disable_archive,
    on_chat_event,
    _get_active_archive,
    _count_lines_and_last_ts,
    _finalize_archive,
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
    msg = ChatMessage(source="+123", source_name="+123", destination="chat123", type=MessageType.CHAT, text="Hello")
    with patch("os.makedirs") as mock_makedirs:
        await on_chat_event(msg)
        mock_makedirs.assert_not_called()

@pytest.mark.asyncio
async def test_on_chat_event_chat_message():
    chat_id = "chat123"
    archiver_main.enabled_chats.add(chat_id)
    msg = ChatMessage(source="+123", source_name="+123", destination=chat_id, type=MessageType.CHAT, text="Hello", timestamp=1000)

    with patch("plugins.archiver.main.get_safe_chat_dir", return_value="/tmp/chat123") as mock_get_dir, \
         patch("os.makedirs") as mock_makedirs, \
         patch("plugins.archiver.main.glob.glob", return_value=[]) as mock_glob, \
         patch("builtins.open", mock_open()) as mock_file:

        await on_chat_event(msg)

        mock_get_dir.assert_called_once_with(ARCHIVES_DIR, chat_id)
        mock_makedirs.assert_called_with("/tmp/chat123", exist_ok=True)
        mock_glob.assert_called_once_with(os.path.join("/tmp/chat123", "*-.jsonl"))
        mock_file.assert_called_with(os.path.join("/tmp/chat123", "1000-.jsonl"), "a", encoding="utf-8")

        handle = mock_file()
        written_line = handle.write.call_args[0][0]
        data = json.loads(written_line)
        assert data["text"] == "Hello"
        assert data["type"] == "chat"

@pytest.mark.asyncio
async def test_on_chat_event_edit_message():
    chat_id = "chat123"
    archiver_main.enabled_chats.add(chat_id)
    msg = EditMessage(source="+123", source_name="+123", destination=chat_id, type=MessageType.EDIT, text="Edited", timestamp=2000, target_sent_timestamp=1000)

    with patch("plugins.archiver.main.get_safe_chat_dir", return_value="/tmp/chat123"), \
         patch("os.makedirs"), \
         patch("plugins.archiver.main.glob.glob", return_value=[]), \
         patch("builtins.open", mock_open()) as mock_file:

        await on_chat_event(msg)

        mock_file.assert_called_with(os.path.join("/tmp/chat123", "2000-.jsonl"), "a", encoding="utf-8")
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
    msg = DeleteMessage(source="+123", source_name="+123", destination=chat_id, type=MessageType.DELETE, timestamp=3000, target_sent_timestamp=1000)

    with patch("plugins.archiver.main.get_safe_chat_dir", return_value="/tmp/chat123"), \
         patch("os.makedirs"), \
         patch("plugins.archiver.main.glob.glob", return_value=[]), \
         patch("builtins.open", mock_open()) as mock_file:

        await on_chat_event(msg)

        mock_file.assert_called_with(os.path.join("/tmp/chat123", "3000-.jsonl"), "a", encoding="utf-8")
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
    msg = ChatMessage(source="+123", source_name="+123", destination=chat_id, type=MessageType.CHAT, text="Image", timestamp=1000, attachments=[att])

    with patch("plugins.archiver.main.get_safe_chat_dir", return_value="/tmp/chat123"), \
         patch("os.makedirs") as mock_makedirs, \
         patch("plugins.archiver.main.glob.glob", return_value=[]), \
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
    msg = ChatMessage(source="+123", source_name="+123", destination=chat_id, type=MessageType.CHAT, text="Hello")

    with patch("plugins.archiver.main.get_safe_chat_dir", side_effect=Exception("Generic error")), \
         patch("plugins.archiver.main.logger") as mock_logger:

        await on_chat_event(msg)
        mock_logger.error.assert_called_once()
        assert "Error archiving message" in mock_logger.error.call_args[0][0]

@pytest.mark.asyncio
async def test_on_chat_event_rolling_file():
    """When the active file is full, it is finalized and a new one is started."""
    chat_id = "chat123"
    archiver_main.enabled_chats.add(chat_id)
    msg = ChatMessage(source="+123", source_name="+123", destination=chat_id, type=MessageType.CHAT, text="New", timestamp=5000)

    active_file = "/tmp/chat123/1000-.jsonl"
    last_line = json.dumps({"timestamp": 4999})

    with patch("plugins.archiver.main.get_safe_chat_dir", return_value="/tmp/chat123"), \
         patch("os.makedirs"), \
         patch("plugins.archiver.main.glob.glob", return_value=[active_file]), \
         patch("plugins.archiver.main._count_lines_and_last_ts", return_value=(100, 4999)), \
         patch("plugins.archiver.main._finalize_archive") as mock_finalize, \
         patch("builtins.open", mock_open()) as mock_file:

        await on_chat_event(msg)

        mock_finalize.assert_called_once_with(active_file, 4999)
        mock_file.assert_called_with(os.path.join("/tmp/chat123", "5000-.jsonl"), "a", encoding="utf-8")

@pytest.mark.asyncio
async def test_on_chat_event_active_file_not_full():
    """When the active file is not yet full, messages continue to be appended to it."""
    chat_id = "chat123"
    archiver_main.enabled_chats.add(chat_id)
    msg = ChatMessage(source="+123", source_name="+123", destination=chat_id, type=MessageType.CHAT, text="Another", timestamp=2000)

    active_file = "/tmp/chat123/1000-.jsonl"

    with patch("plugins.archiver.main.get_safe_chat_dir", return_value="/tmp/chat123"), \
         patch("os.makedirs"), \
         patch("plugins.archiver.main.glob.glob", return_value=[active_file]), \
         patch("plugins.archiver.main._count_lines_and_last_ts", return_value=(50, 1999)), \
         patch("plugins.archiver.main._finalize_archive") as mock_finalize, \
         patch("plugins.archiver.main.plugin_settings.max_messages_per_file", 100), \
         patch("builtins.open", mock_open()) as mock_file:

        await on_chat_event(msg)

        mock_finalize.assert_not_called()
        mock_file.assert_called_with(active_file, "a", encoding="utf-8")

def test_finalize_archive():
    with patch("os.rename") as mock_rename:
        _finalize_archive("/tmp/chat123/1000-.jsonl", 4999)
        mock_rename.assert_called_once_with(
            "/tmp/chat123/1000-.jsonl",
            "/tmp/chat123/1000-4999.jsonl"
        )

def test_count_lines_and_last_ts():
    lines = [
        json.dumps({"timestamp": 100, "text": "a"}),
        json.dumps({"timestamp": 200, "text": "b"}),
        json.dumps({"timestamp": 300, "text": "c"}),
    ]
    file_content = "\n".join(lines) + "\n"
    with patch("builtins.open", mock_open(read_data=file_content)):
        count, last_ts = _count_lines_and_last_ts("somefile.jsonl")
    assert count == 3
    assert last_ts == 300

def test_get_active_archive():
    with patch("plugins.archiver.main.glob.glob", return_value=["/tmp/chat123/1000-.jsonl"]):
        result = _get_active_archive("/tmp/chat123")
    assert result == "/tmp/chat123/1000-.jsonl"

def test_get_active_archive_none():
    with patch("plugins.archiver.main.glob.glob", return_value=[]):
        result = _get_active_archive("/tmp/chat123")
    assert result is None
