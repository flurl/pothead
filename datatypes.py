"""
This module defines the core data structures and types used throughout the application.

It includes dataclasses for representing Signal messages (`ChatMessage`, `Attachment`,
`MessageQuote`), configuration structures (`Command`, `Action`), and enumerations
(`Priority`, `Event`). It also handles parsing logic for converting raw JSON
data from `signal-cli` into structured objects.
"""

from dataclasses import dataclass, field
import json
import datetime
from typing import Any, Self, TypeAlias, cast
from collections.abc import Awaitable, Callable
from enum import Enum
import logging

import jsonpath_ng.ext

logger: logging.Logger = logging.getLogger(__name__)

Permissions: TypeAlias = dict[str, dict[str, list[str] | dict[str, list[str]]]]


@dataclass
class Attachment:
    """
    Represents a file attachment in a Signal message.

    Attributes:
        content_type: The MIME type of the attachment.
        id: The unique identifier of the attachment.
        size: The size of the attachment in bytes.
        filename: The original filename of the attachment, if available.
        width: The width of the image (if applicable).
        height: The height of the image (if applicable).
        caption: The caption associated with the attachment.
    """
    content_type: str
    id: str
    size: int
    filename: str | None = None
    width: int | None = None
    height: int | None = None
    caption: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        """Creates an Attachment instance from a dictionary."""
        return cls(
            content_type=data.get("contentType", "unknown"),
            id=data.get("id", ""),
            size=data.get("size", 0),
            filename=data.get("filename"),
            width=data.get("width"),
            height=data.get("height"),
            caption=data.get("caption")
        )


@dataclass
class MessageQuote:
    """
    Represents a quoted message within a Signal message.

    Attributes:
        id: The timestamp ID of the quoted message.
        author: The author of the quoted message.
        author_number: The phone number of the author.
        author_uuid: The UUID of the author.
        text: The text content of the quoted message.
        attachments: A list of attachments in the quoted message.
    """
    id: int
    author: str
    author_number: str
    author_uuid: str
    text: str | None = None
    attachments: list[Attachment] | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        """Creates a MessageQuote instance from a dictionary."""
        return cls(
            id=data.get("id", 0),
            author=data.get("author", ""),
            author_number=data.get("authorNumber", ""),
            author_uuid=data.get("authorUuid", ""),
            text=data.get("text"),
            attachments=[Attachment.from_dict(a)
                         for a in data.get("attachments", [])]
        )


class MessageType(Enum):
    """
    Enum to distinguish between different message types.
    """
    CHAT = "chat"
    REACTION = "reaction"
    RECEIPT = "receipt"
    TYPING = "typing"
    UNKNOWN = "unknown"


@dataclass
class SignalMessage:
    """
    Base class for all Signal messages.
    """
    source: str
    type: MessageType
    timestamp: int = field(default_factory=lambda: int(
        datetime.datetime.now().timestamp() * 1000))
    group_id: str | None = None
    is_synced: bool = False

    @property
    def id(self) -> str:
        """Returns a unique identifier for the message."""
        return f"{self.source}${self.timestamp}"

    @classmethod
    def from_json(cls, data: dict[str, Any] | str) -> "SignalMessage | None":
        """
        Parses a JSON dictionary or string from signal-cli into a SignalMessage object.
        """
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except json.JSONDecodeError:
                return None

        params: dict[str, Any] = cast(dict[str, Any], data).get("params", {})
        envelope: dict[str, Any] = params.get("envelope", {})
        source: str | None = envelope.get("source")

        if source is None:
            return None

        # messages from others to me
        if "dataMessage" in envelope:
            data_message: dict[str, Any] = envelope.get("dataMessage", {})
            return ChatMessage.parse_message(data_message, source, is_synced=False)
        elif "syncMessage" in envelope:
            if "sentMessage" in envelope["syncMessage"]:
                sent_message: dict[str,
                                   Any] = envelope["syncMessage"]["sentMessage"]
                return ChatMessage.parse_message(sent_message, source, is_synced=True)
        elif "receiptMessage" in envelope:
            return ReceiptMessage.parse_receipt_message(envelope, source)
        elif "typingMessage" in envelope:
            return TypingMessage.parse_typing_message(envelope, source)

        return None


@dataclass
class ChatMessage(SignalMessage):
    """
    Standardized representation of a chat message.

    Attributes:
        source: The sender of the message (inherited).
        type: The type of the message (inherited).
        timestamp: The timestamp of the message (inherited).
        group_id: The group ID (inherited).
        is_synced: Whether the message was synced (inherited).
        destination: The recipient of the message.
        text: The text content of the message.
        attachments: A list of attachments in the message.
        quote: The quoted message, if any.
    """
    destination: str | None = None
    text: str | None = None
    attachments: list[Attachment] | None = None
    quote: MessageQuote | None = None

    @property
    def chat_id(self) -> str:
        """Returns the ID of the chat context (group ID or sender)."""
        return self.destination if self.destination else self.source

    def __str__(self) -> str:
        sender_info: str = self.source
        if self.destination:
            sender_info += f" -> {self.destination}"
        elif self.group_id:
            sender_info += f" (Group: {self.group_id})"

        msg_repr: str = f"[{datetime.datetime.fromtimestamp(self.timestamp / 1000).strftime('%Y-%m-%d %H:%M:%S')}] [{self.type.value.upper()}] {sender_info}"
        if self.text:
            msg_repr += f"\nText: {self.text}"
        if self.attachments:
            msg_repr += f"\nAttachments: {len(self.attachments)}"
            for att in self.attachments:
                msg_repr += f"\n  - {att.filename or att.id} ({att.content_type})"
                if att.caption:
                    msg_repr += f" (Caption: {att.caption})"
        if self.quote:
            msg_repr += f"\nQuote (from {self.quote.author}): {self.quote.text or '[No text]'}"
        return msg_repr

    @classmethod
    def parse_message(cls, message_body: dict[str, Any], source: str, is_synced: bool = False) -> "SignalMessage | None":
        timestamp: int | None = message_body.get("timestamp", None)
        if timestamp is None:
            return None

        if "reaction" in message_body:
            return ReactionMessage.parse_reaction(message_body, source, timestamp, MessageType.REACTION)

        group_id: str | None = message_body.get("groupInfo", {}).get("groupId")
        destination: str | None = message_body.get("destination")
        if not destination:
            destination = group_id

        text: str | None = message_body.get("message")
        attachments: list[Attachment] = [Attachment.from_dict(
            a) for a in message_body.get("attachments", [])]
        raw_quote: dict[str, Any] | None = message_body.get("quote")
        quote: MessageQuote | None = MessageQuote.from_dict(
            raw_quote) if raw_quote else None

        return cls(source=source, type=MessageType.CHAT, timestamp=timestamp, group_id=group_id, destination=destination, text=text, attachments=attachments, quote=quote, is_synced=is_synced)


@dataclass(kw_only=True)
class ReactionMessage(SignalMessage):
    emoji: str
    target_author: str
    target_sent_timestamp: int
    is_remove: bool

    @classmethod
    def parse_reaction(cls, message_body: dict[str, Any], source: str, timestamp: int, msg_type: MessageType) -> "ReactionMessage":
        reaction: dict[str, Any] = message_body.get("reaction", {})
        group_id: str | None = message_body.get("groupInfo", {}).get("groupId")
        return cls(
            source=source,
            type=msg_type,
            timestamp=timestamp,
            group_id=group_id,
            emoji=reaction.get("emoji", ""),
            target_author=reaction.get("targetAuthor", ""),
            target_sent_timestamp=reaction.get("targetSentTimestamp", 0),
            is_remove=reaction.get("remove", False)
        )


@dataclass
class ReceiptMessage(SignalMessage):
    timestamps: list[int] = field(kw_only=True)
    is_delivery: bool = False
    is_read: bool = False
    is_viewed: bool = False

    @classmethod
    def parse_receipt_message(cls, envelope: dict[str, Any], source: str) -> "ReceiptMessage | None":
        receipt: dict[str, Any] = envelope.get("receiptMessage", {})
        timestamps: list[int] = receipt.get("timestamps", [])
        if not timestamps:
            return None
        when: int = receipt.get("when", int(
            datetime.datetime.now().timestamp() * 1000))
        return cls(
            source=source,
            type=MessageType.RECEIPT,
            timestamp=when,
            timestamps=timestamps,
            is_delivery=receipt.get("isDelivery", False),
            is_read=receipt.get("isRead", False),
            is_viewed=receipt.get("isViewed", False)
        )


@dataclass
class TypingMessage(SignalMessage):
    action: str = field(kw_only=True)

    @classmethod
    def parse_typing_message(cls, envelope: dict[str, Any], source: str) -> "TypingMessage | None":
        typing: dict[str, Any] = envelope.get("typingMessage", {})
        timestamp: int | None = typing.get("timestamp")
        if timestamp is None:
            return None
        return cls(
            source=source,
            type=MessageType.TYPING,
            timestamp=timestamp,
            group_id=typing.get("groupId"),
            action=typing.get("action", "UNKNOWN")
        )


class Priority(Enum):
    """
    Enum to define the priority of actions.
    Higher value means higher priority.
    """
    LOW = 1
    NORMAL = 2
    HIGH = 3
    SYS = 4


@dataclass
class Action:
    """
    Represents an action to be taken when an incoming message matches specific criteria.

    Attributes:
        name: A descriptive name for the action.
        jsonpath: A JSONPath expression string used to locate specific data within the incoming JSON message.
                  Uses `jsonpath_ng.ext` for extended features.
        origin: To which component the action belongs to.
        handler: An asynchronous callable that is executed if the action matches.
                 It receives the `Process` object and the data dictionary as arguments.
                 It must return a boolean indicating whether the message was handled. True means
                 the message was handeled successfully annd should not be further processed.
                 False means that the message wasn't processed at all or that it might have
                 been processed but further processing is OK
        priority: The execution priority of the action. Actions are sorted by priority before execution.
                  Default is `Priority.NORMAL`.
        filter: An optional callable that receives the value found by the JSONPath expression.
                It must return `True` for the action to be considered a match.
                If None, existence of the JSONPath match is sufficient.
    """
    name: str
    jsonpath: str
    origin: str
    handler: Callable[[dict[str, Any]], Awaitable[bool]]
    priority: Priority = Priority.NORMAL
    filter: Callable[[Any], bool] | None = None
    _compiled_path: Any = field(init=False)

    def __post_init__(self) -> None:
        self._compiled_path = jsonpath_ng.ext.parse(self.jsonpath)  # pyright: ignore[reportAttributeAccessIssue, reportUnknownMemberType] # nopep8

    def matches(self, data: dict[str, Any]) -> bool:
        try:
            matches: Any = self._compiled_path.find(data)
            if not matches:
                return False
            if self.filter:
                for match in matches:
                    try:
                        if self.filter(match):
                            logger.debug(f"Action '{self.name}' matched.")
                            return True
                    except Exception as e:
                        logger.error(
                            f"Action '{self.name}': Filter error: {e}")
                return False
            logger.debug(f"Action '{self.name}' matched.")
            return True
        except Exception as e:
            logger.error(f"Action '{self.name}': Match error: {e}")
            return False


@dataclass
class Command:
    """
    Represents a registered command.

    Attributes:
        name: The name of the command.
        handler: The asynchronous function that handles the command.
        help_text: A description of the command.
        origin: The origin of the command (e.g., 'sys' or a plugin ID).
    """
    name: str
    handler: Callable[[str, list[str], str | None],
                      Awaitable[tuple[str, list[str]]]]
    help_text: str
    origin: str


class Event(Enum):
    """
    Enum to define the available events
    """
    POST_STARTUP = "post_startup"
    PRE_SHUTDOWN = "pre_shutdown"
    TIMER = "timer"
    CHAT_MESSAGE_RECEIVED = "message_received"
