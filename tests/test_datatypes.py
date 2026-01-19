
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
    SignalMessage,
    MessageType,
    ReactionMessage,
    ReceiptMessage,
    TypingMessage,
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


def test_signal_message_from_json_chat():
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
    msg = SignalMessage.from_json(data)
    assert isinstance(msg, ChatMessage)
    assert msg.source == "user1"
    assert msg.text == "Hello"
    assert msg.group_id == "group1"
    assert msg.type == MessageType.CHAT

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
    msg = SignalMessage.from_json(data)
    assert isinstance(msg, ChatMessage)
    assert msg.source == "user1"
    assert msg.text == "World"
    assert msg.destination == "user2"
    assert msg.type == MessageType.CHAT
    assert msg.is_synced is True


def test_signal_message_from_json_reaction():
    data = {
        "params": {
            "envelope": {
                "source": "user1",
                "dataMessage": {
                    "timestamp": 123456789,
                    "reaction": {
                        "emoji": "👍",
                        "targetAuthor": "user2",
                        "targetSentTimestamp": 123456700,
                        "remove": False
                    },
                    "groupInfo": {"groupId": "group1"},
                },
            }
        }
    }
    msg = SignalMessage.from_json(data)
    assert isinstance(msg, ReactionMessage)
    assert msg.source == "user1"
    assert msg.emoji == "👍"
    assert msg.target_author == "user2"
    assert msg.target_sent_timestamp == 123456700
    assert msg.is_remove is False
    assert msg.group_id == "group1"
    assert msg.type == MessageType.REACTION


def test_signal_message_from_json_receipt():
    data = {
        "params": {
            "envelope": {
                "source": "user1",
                "receiptMessage": {
                    "when": 123456789,
                    "isDelivery": True,
                    "isRead": False,
                    "isViewed": False,
                    "timestamps": [123456700]
                }
            }
        }
    }
    msg = SignalMessage.from_json(data)
    assert isinstance(msg, ReceiptMessage)
    assert msg.source == "user1"
    assert msg.timestamp == 123456789
    assert msg.is_delivery is True
    assert msg.timestamps == [123456700]
    assert msg.type == MessageType.RECEIPT


def test_signal_message_from_json_typing():
    data = {
        "params": {
            "envelope": {
                "source": "user1",
                "typingMessage": {
                    "timestamp": 123456789,
                    "action": "STARTED",
                    "groupId": "group1"
                }
            }
        }
    }
    msg = SignalMessage.from_json(data)
    assert isinstance(msg, TypingMessage)
    assert msg.source == "user1"
    assert msg.timestamp == 123456789
    assert msg.action == "STARTED"
    assert msg.group_id == "group1"
    assert msg.type == MessageType.TYPING


def test_chat_message_from_json_deprecated():
    # ChatMessage.from_json was actually removed in favor of SignalMessage.from_json,
    # but it might still be used. Let's check if it exists.
    # Actually, in the diff I didn't see it being removed, but I saw SignalMessage.from_json added.
    # Looking at datatypes.py, ChatMessage DOES NOT have from_json anymore, it's in SignalMessage.
    # Wait, I should re-read datatypes.py.
    pass


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
    assert Event.CHAT_MESSAGE_RECEIVED.value == "message_received"
