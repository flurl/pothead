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
    name: str
    jsonpath: str
    handler: Callable[[Any, dict[str, Any]], Awaitable[None]]
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
