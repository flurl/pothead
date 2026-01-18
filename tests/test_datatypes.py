
import pytest
from unittest.mock import AsyncMock, MagicMock
from datatypes import (
    Attachment,
    MessageQuote,
    ChatMessage,
    Action,
    Priority,
    Command,
    Event,
)


def test_attachment_from_dict():
    data = {"contentType": "image/png", "id": "123",
            "size": 1024, "filename": "test.png"}
    att = Attachment.from_dict(data)
    assert att.content_type == "image/png"
    assert att.id == "123"
    assert att.size == 1024
    assert att.filename == "test.png"


def test_message_quote_from_dict():
    data = {"id": 1, "author": "user1", "authorNumber": "123",
            "authorUuid": "abc", "text": "Hello"}
    quote = MessageQuote.from_dict(data)
    assert quote.id == 1
    assert quote.author == "user1"
    assert quote.text == "Hello"


def test_chat_message_from_json():
    # Test with dataMessage
    data = {
        "params": {
            "envelope": {
                "source": "user1",
                "dataMessage": {
                    "timestamp": 123456789,
                    "message": "Hello",
                    "groupInfo": {"groupId": "group1"},
                },
            }
        }
    }
    msg = ChatMessage.from_json(data)
    assert msg is not None
    assert msg.source == "user1"
    assert msg.text == "Hello"
    assert msg.group_id == "group1"

    # Test with syncMessage
    data = {
        "params": {
            "envelope": {
                "source": "user1",
                "syncMessage": {
                    "sentMessage": {
                        "timestamp": 123456789,
                        "message": "World",
                        "destination": "user2",
                    }
                },
            }
        }
    }
    msg = ChatMessage.from_json(data)
    assert msg is not None
    assert msg.source == "user1"
    assert msg.text == "World"
    assert msg.destination == "user2"


def test_action_matches():
    handler = AsyncMock()
    action = Action(
        name="Test Action",
        jsonpath="$.params.message",
        origin="sys",
        handler=handler,
        filter=lambda x: x.value == "Hello",
    )
    data = {"params": {"message": "Hello"}}
    assert action.matches(data)
    data = {"params": {"message": "World"}}
    assert not action.matches(data)


def test_command():
    handler = AsyncMock()
    command = Command(name="test", handler=handler,
                      help_text="A test command", origin="sys")
    assert command.name == "test"
    assert command.handler == handler
    assert command.help_text == "A test command"
    assert command.origin == "sys"


def test_event_enum():
    assert Event.POST_STARTUP.value == "post_startup"
    assert Event.PRE_SHUTDOWN.value == "pre_shutdown"
    assert Event.TIMER.value == "timer"
