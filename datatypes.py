from dataclasses import dataclass
from typing import TypeAlias


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
