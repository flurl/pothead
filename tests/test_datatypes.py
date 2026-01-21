
import pytest
import json
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
    EditMessage,
    DeleteMessage,
    GroupUpdateMessage,
)


def test_attachment_from_dict():
    data = {"contentType": "image/png", "id": "123",
            "size": 1024, "filename": "test.png", "width": 100, "height": 100, "caption": "cap"}
    att = Attachment.from_dict(data)
    assert att.content_type == "image/png"
    assert att.id == "123"
    assert att.size == 1024
    assert att.filename == "test.png"
    assert att.width == 100
    assert att.height == 100
    assert att.caption == "cap"

def test_attachment_from_dict_defaults():
    att = Attachment.from_dict({})
    assert att.content_type == "unknown"
    assert att.id == ""
    assert att.size == 0

def test_message_quote_from_dict():
    data = {"id": 1, "author": "user1", "authorNumber": "123",
            "authorUuid": "abc", "text": "Hello", "attachments": [{"id": "a1", "size": 1}]}
    quote = MessageQuote.from_dict(data)
    assert quote.id == 1
    assert quote.author == "user1"
    assert quote.text == "Hello"
    assert len(quote.attachments) == 1
    assert quote.attachments[0].id == "a1"


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

def test_signal_message_from_json_edit():
    data = {
        "params": {
            "envelope": {
                "source": "user1",
                "editMessage": {
                    "targetSentTimestamp": 123,
                    "dataMessage": {
                        "timestamp": 456,
                        "message": "New Text"
                    }
                }
            }
        }
    }
    msg = SignalMessage.from_json(data)
    assert isinstance(msg, EditMessage)
    assert msg.target_sent_timestamp == 123
    assert msg.text == "New Text"

def test_signal_message_from_json_edit_sync():
    data = {
        "params": {
            "envelope": {
                "source": "user1",
                "syncMessage": {
                    "sentMessage": {
                        "editMessage": {
                            "targetSentTimestamp": 123,
                            "dataMessage": {
                                "timestamp": 456,
                                "message": "New Text Sync"
                            }
                        }
                    }
                }
            }
        }
    }
    msg = SignalMessage.from_json(data)
    assert isinstance(msg, EditMessage)
    assert msg.is_synced is True
    assert msg.text == "New Text Sync"

def test_signal_message_from_json_invalid():
    assert SignalMessage.from_json("invalid") is None
    assert SignalMessage.from_json({}) is None
    assert SignalMessage.from_json({"params": {"envelope": {}}}) is None

def test_signal_message_from_json_string():
    data_str = json.dumps({
        "params": {
            "envelope": {
                "source": "user1",
                "dataMessage": {"timestamp": 123, "message": "hi"}
            }
        }
    })
    msg = SignalMessage.from_json(data_str)
    assert msg.text == "hi"


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

def test_signal_message_from_json_receipt_no_timestamps():
    data = {"params": {"envelope": {"source": "u", "receiptMessage": {"timestamps": []}}}}
    assert SignalMessage.from_json(data) is None


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

def test_signal_message_from_json_delete():
    data = {
        "params": {
            "envelope": {
                "source": "user1",
                "dataMessage": {
                    "timestamp": 123,
                    "remoteDelete": {"timestamp": 456}
                }
            }
        }
    }
    msg = SignalMessage.from_json(data)
    assert isinstance(msg, DeleteMessage)
    assert msg.target_sent_timestamp == 456

def test_signal_message_from_json_group_update():
    data = {
        "params": {
            "envelope": {
                "source": "user1",
                "dataMessage": {
                    "timestamp": 123,
                    "groupInfo": {"groupId": "g1", "type": "UPDATE", "groupName": "New Name", "revision": 5}
                }
            }
        }
    }
    msg = SignalMessage.from_json(data)
    assert isinstance(msg, GroupUpdateMessage)
    assert msg.group_id == "g1"
    assert msg.group_name == "New Name"
    assert msg.revision == 5


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

def test_action_matches_no_filter():
    handler = AsyncMock()
    action = Action(
        name="Test Action",
        jsonpath="$.params.message",
        origin="sys",
        handler=handler
    )
    data = {"params": {"message": "Any"}}
    assert action.matches(data)
    data = {"params": {"other": "Any"}}
    assert not action.matches(data)

def test_action_matches_error():
    action = Action(name="n", jsonpath="$.p", origin="o", handler=AsyncMock(), filter=lambda x: 1/0)
    assert not action.matches({"p": "v"})


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
    assert Event.CHAT_MESSAGE_EDITED.value == "message_edited"
    assert Event.CHAT_MESSAGE_DELETED.value == "message_deleted"
    assert Event.GROUP_UPDATE.value == "group_update"

def test_chat_message_str():
    msg = ChatMessage(source="user1", text="Hello", type=MessageType.CHAT, timestamp=1000000000)
    s = str(msg)
    assert "user1" in s
    assert "Hello" in s

    msg.destination = "dest"
    assert "user1 -> dest" in str(msg)

    msg.destination = None
    msg.group_id = "group"
    assert "(Group: group)" in str(msg)

    msg.attachments = [Attachment(id="a1", content_type="text/plain", size=1, caption="c")]
    assert "Attachments: 1" in str(msg)
    assert "Caption: c" in str(msg)

    msg.quote = MessageQuote(id=1, author="auth", author_number="n", author_uuid="u", text="q")
    assert "Quote (from auth): q" in str(msg)
