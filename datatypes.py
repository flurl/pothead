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
    content_type: str
    id: str
    size: int
    filename: str | None = None
    width: int | None = None
    height: int | None = None
    caption: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
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
    id: int
    author: str
    author_number: str
    author_uuid: str
    text: str | None = None
    attachments: list[Attachment] | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
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
    source: str
    destination: str | None
    text: str | None
    attachments: list[Attachment] | None = None
    quote: MessageQuote | None = None
    # if it's a message to or from a group there will be a group_id
    group_id: str | None = None

    @property
    def chat_id(self) -> str:
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
            quote: MessageQuote | None = data_message.get("quote", None)
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
            quote: MessageQuote | None = sent_message.get("quote", None)
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
    name: str
    handler: Callable[[str, list[str], str | None],
                      Awaitable[tuple[str, list[str]]]]
    help_text: str
    origin: str
