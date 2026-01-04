from dataclasses import dataclass, field
from typing import Any, TypeAlias
from collections.abc import Awaitable, Callable
from enum import Enum

import jsonpath_ng.ext

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


@dataclass
class ChatMessage:
    sender: str
    text: str | None
    attachments: list[Attachment]

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
        handler: An asynchronous callable that is executed if the action matches.
                 It receives the `Process` object and the data dictionary as arguments.
        priority: The execution priority of the action. Actions are sorted by priority before execution.
                  Default is `Priority.NORMAL`.
        halt: If True, stops the processing of subsequent actions in the loop if this action matches.
              Default is False.
        filter: An optional callable that receives the value found by the JSONPath expression.
                It must return `True` for the action to be considered a match.
                If None, existence of the JSONPath match is sufficient.
    """
    name: str
    jsonpath: str
    origin: str
    handler: Callable[[dict[str, Any]], Awaitable[None]]
    priority: Priority = Priority.NORMAL
    halt: bool = False
    filter: Callable[[Any], bool] | None = None
    _compiled_path: Any = field(init=False)

    def __post_init__(self) -> None:
        self._compiled_path = jsonpath_ng.ext.parse(self.jsonpath)  # pyright: ignore[reportAttributeAccessIssue, reportUnknownMemberType] # nopep8

    def matches(self, data: dict[str, Any]) -> bool:
        matches: Any = self._compiled_path.find(data)
        if not matches:
            return False
        if self.filter:
            return any(self.filter(match.value) for match in matches)
        return True


@dataclass
class Command:
    name: str
    handler: Callable[[str, list[str], str | None],
                      Awaitable[tuple[str, list[str]]]]
    help_text: str
    origin: str
