"""
This module defines the core data structures and types used throughout the application.

It includes dataclasses for representing Signal messages (`ChatMessage`, `Attachment`,
`MessageQuote`), configuration structures (`Command`, `Action`), and enumerations
(`Priority`, `Event`). It also handles parsing logic for converting raw JSON
data from `signal-cli` into structured objects.
"""

from dataclasses import dataclass, field
import json
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


@dataclass
class ChatMessage:
    """
    Standardized representation of a chat message.

    Attributes:
        source: The sender of the message.
        destination: The recipient of the message.
        text: The text content of the message.
        attachments: A list of attachments in the message.
        quote: The quoted message, if any.
        group_id: The group ID, if the message is associated with a group.
    """
    source: str
    destination: str | None = None
    text: str | None = None
    attachments: list[Attachment] | None = None
    quote: MessageQuote | None = None
    # if it's a message to or from a group there will be a group_id
    group_id: str | None = None

    @property
    def chat_id(self) -> str:
        """Returns the ID of the chat context (group ID or sender)."""
        return self.destination if self.destination else self.source

    def __str__(self) -> str:
        out: list[str] = []
        if self.text:
            out.append(self.text)
        if self.attachments:
            out.append(f"[Attachments: {len(self.attachments)}]")
            for att in self.attachments:
                name: str = att.filename if att.filename else att.id
                details: str = f"{name} ({att.content_type})"
                if att.caption:
                    details += f" Caption: {att.caption}"
                out.append(f"  - {details}")
        return "\n".join(out)

    @classmethod
    def from_json(cls, data: dict[str, Any] | str) -> Self | None:
        """
        Parses a JSON dictionary or string from signal-cli into a ChatMessage object.

        Handles both 'dataMessage' (incoming messages) and 'syncMessage' (messages sent from other devices).
        Returns None if the data is not a valid message or cannot be parsed.
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

        group_id: str | None = None

        if "dataMessage" in envelope:
            data_message: dict[str, Any] = envelope.get("dataMessage", {})
            destination: str | None = data_message.get("groupInfo", {}).get(
                "groupId", None)
            group_id = destination
            text: str | None = data_message.get("message")
            attachments: list[Attachment] = [Attachment.from_dict(
                a) for a in data_message.get("attachments", [])]
            raw_quote: dict[str, Any] | None = data_message.get("quote")
            quote: MessageQuote | None = MessageQuote.from_dict(
                raw_quote) if raw_quote else None
        elif "syncMessage" in envelope:
            sent_message: dict[str, Any] = envelope.get(
                "syncMessage", {}).get("sentMessage", {})

            if not sent_message:
                return None

            destination: str | None = sent_message.get("destination")
            if not destination and "groupInfo" in sent_message:
                group_info: dict[str, Any] = sent_message.get("groupInfo", {})
                destination = group_info.get("groupId")
                group_id = destination
            text: str | None = sent_message.get("message")
            attachments: list[Attachment] = [Attachment.from_dict(
                a) for a in sent_message.get("attachments", [])]
            raw_quote: dict[str, Any] | None = sent_message.get("quote")
            quote: MessageQuote | None = MessageQuote.from_dict(
                raw_quote) if raw_quote else None
        else:
            return None

        return cls(source=source, destination=destination, text=text, attachments=attachments, quote=quote, group_id=group_id)


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
