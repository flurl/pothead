
import asyncio
import json
from unittest.mock import AsyncMock, patch, MagicMock
import pytest
from datatypes import ChatMessage, MessageType
from messaging import (
    send_signal_direct_message,
    send_signal_group_message,
    send_signal_message,
    get_group_info,
    set_signal_process,
    parse_markdown,
)
from config import settings


@pytest.mark.asyncio
async def test_send_signal_direct_message():
    with patch("messaging.send_signal_message", new_callable=AsyncMock) as mock_send:
        await send_signal_direct_message("Hello", "user1")
        mock_send.assert_called_once()
        sent_msg = mock_send.call_args[0][0]
        assert isinstance(sent_msg, ChatMessage)
        assert sent_msg.text == "Hello"
        assert sent_msg.destination == "user1"


@pytest.mark.asyncio
async def test_send_signal_group_message():
    with patch("messaging.send_signal_message", new_callable=AsyncMock) as mock_send:
        await send_signal_group_message("Hello", "group1")
        mock_send.assert_called_once()
        sent_msg = mock_send.call_args[0][0]
        assert isinstance(sent_msg, ChatMessage)
        assert sent_msg.text == "Hello"
        assert sent_msg.group_id == "group1"


@pytest.mark.asyncio
async def test_send_signal_message():
    mock_proc = AsyncMock()
    mock_proc.stdin = MagicMock()
    mock_proc.stdin.drain = AsyncMock()
    set_signal_process(mock_proc)

    msg = ChatMessage(source="Assistant", destination="user1",
                      text="Hello", type=MessageType.CHAT)
    await send_signal_message(msg)

    mock_proc.stdin.write.assert_called_once()
    written_data = mock_proc.stdin.write.call_args[0][0]
    rpc_request = json.loads(written_data)
    assert rpc_request["method"] == "send"
    assert rpc_request["params"]["recipient"] == ["user1"]
    mock_proc.stdin.drain.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_group_info():
    mock_proc = AsyncMock()
    mock_proc.stdin = MagicMock()
    mock_proc.stdin.drain = AsyncMock()
    set_signal_process(mock_proc)

    callback = AsyncMock()
    with patch("messaging.PENDING_REPLIES", {}) as mock_pending_replies:
        await get_group_info("group1", callback)
        assert len(mock_pending_replies) == 1
        request_id = list(mock_pending_replies.keys())[0]
        assert mock_pending_replies[request_id] == callback

        mock_proc.stdin.write.assert_called_once()
        written_data = mock_proc.stdin.write.call_args[0][0]
        rpc_request = json.loads(written_data)
        assert rpc_request["method"] == "listGroups"
        assert rpc_request["params"]["groupId"] == "group1"
        assert rpc_request["id"] == request_id
        mock_proc.stdin.drain.assert_awaited_once()


def test_parse_markdown():
    # Test simple bold
    text, styles = parse_markdown("Hello **World**")
    assert text == "Hello World"
    assert styles == ["6:5:BOLD"]

    # Test multiple styles
    text, styles = parse_markdown("`Code` and *Italic*")
    assert text == "Code and Italic"
    assert "0:4:MONOSPACE" in styles
    assert "9:6:ITALIC" in styles

    # Test nested styles
    text, styles = parse_markdown("**Bold *Italic***")
    assert text == "Bold Italic"
    assert "0:11:BOLD" in styles
    assert "5:6:ITALIC" in styles


def test_parse_markdown_with_emojis():
    # Test with emoji (surrogate pair in UTF-16)
    # 😀 is 1 char in Python but 2 chars in UTF-16
    text, styles = parse_markdown("😀 **Bold**")
    assert text == "😀 Bold"
    # Start should be 3 (2 for emoji + 1 for space), Length 4
    assert styles == ["3:4:BOLD"]


@pytest.mark.asyncio
async def test_send_signal_message_with_formatting():
    mock_proc = AsyncMock()
    mock_proc.stdin = MagicMock()
    mock_proc.stdin.drain = AsyncMock()
    set_signal_process(mock_proc)

    msg = ChatMessage(source="Assistant", destination="user1",
                      text="Hello **World**", type=MessageType.CHAT)
    await send_signal_message(msg)

    mock_proc.stdin.write.assert_called_once()
    written_data = mock_proc.stdin.write.call_args[0][0]
    rpc_request = json.loads(written_data)

    assert rpc_request["method"] == "send"
    assert rpc_request["params"]["recipient"] == ["user1"]
    assert rpc_request["params"]["message"] == f"{settings.message_prefix}Hello World"
    # Check if textStyle is set correctly for a single style
    prefix_length: int = len(settings.message_prefix)
    assert rpc_request["params"]["textStyle"] == f"{6+prefix_length}:5:BOLD"
