
"""
This module handles low-level communication with the `signal-cli` subprocess.

It provides functions to send direct and group messages, request group info,
and manage the `signal-cli` process reference. It encapsulates the JSON-RPC
protocol details required to interact with `signal-cli`.
"""

import json
import logging
import re
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from asyncio.subprocess import Process
from config import settings
from datatypes import ChatMessage, MessageType
from plugin_manager import PENDING_REPLIES

logger: logging.Logger = logging.getLogger(__name__)

signal_process: Process | None = None


@dataclass
class StyleSpan:
    start: int
    length: int
    style: str


def parse_markdown(text: str) -> tuple[str, list[str]]:
    active_styles: list[StyleSpan] = []

    # Patterns: Monospace, Bold, Italic
    patterns: list[tuple[str, str, int]] = [
        (r"`(.*?)`", "MONOSPACE", 1),
        (r"\*\*(.*?)\*\*", "BOLD", 2),
        (r"\*(.*?)\*", "ITALIC", 1)
    ]

    for pattern, style_name, marker_len in patterns:
        while True:
            match: re.Match[str] | None = re.search(
                pattern, text, flags=re.DOTALL)
            if not match:
                break

            start: int = match.start()
            end: int = match.end()
            content: str | Any = match.group(1)
            content_len: int = len(content)

            # Update OLD styles for Left Marker removal
            for s in active_styles:
                if start < s.start:
                    s.start -= marker_len
                elif start < s.start + s.length:
                    s.length -= marker_len

            # Update OLD styles for Right Marker removal
            right_marker_pos: int = end - 2 * marker_len
            for s in active_styles:
                if right_marker_pos < s.start:
                    s.start -= marker_len
                elif right_marker_pos < s.start + s.length:
                    s.length -= marker_len

            # Add NEW style
            active_styles.append(StyleSpan(start, content_len, style_name))

            # Update text
            text = text[:start] + content + text[end:]

    return text, [f"{s.start}:{s.length}:{s.style}" for s in active_styles]


def set_signal_process(proc: Process) -> None:
    global signal_process
    signal_process = proc


async def send_signal_direct_message(
    message: str,
    recipient: str,
    attachments: list[str] | None = None,
    wants_answer_callback: Callable[[
        dict[str, Any]], Awaitable[None]] | None = None
) -> None:
    msg: ChatMessage = ChatMessage(
        source="Assistant", destination=recipient, text=message, type=MessageType.CHAT)
    await send_signal_message(msg, attachments=attachments, wants_answer_callback=wants_answer_callback)


async def send_signal_group_message(
    message: str,
    group_id: str,
    attachments: list[str] | None = None,
    wants_answer_callback: Callable[[
        dict[str, Any]], Awaitable[None]] | None = None
) -> None:
    msg: ChatMessage = ChatMessage(
        source="Assistant", group_id=group_id, text=message, type=MessageType.CHAT)
    await send_signal_message(msg, attachments=attachments, wants_answer_callback=wants_answer_callback)


async def send_signal_message(
    msg: ChatMessage,
    attachments: list[str] | None = None,
    wants_answer_callback: Callable[[
        dict[str, Any]], Awaitable[None]] | None = None
) -> None:
    """
    Sends a message back via signal-cli JSON-RPC.
    Supports direct messages (recipient) and group messages (group_id).
    If wants_answer_callback is provided, it will be called with the response.
    """
    global signal_process
    if not signal_process:
        logger.error("Signal process not initialized.")
        return
    proc: Process = signal_process

    message: str | None = msg.text
    recipient: str | None = msg.destination
    group_id: str | None = msg.group_id

    raw_message: str = settings.message_prefix + (message if message else "")
    clean_message: str
    styles: list[str]
    clean_message, styles = parse_markdown(raw_message)

    params: dict[str, Any] = {
        "account": settings.signal_account,
        "message": clean_message
    }

    if styles:
        if len(styles) == 1:
            params["textStyle"] = styles[0]
        else:
            params["textStyles"] = styles

    if group_id:
        params["groupId"] = group_id
    else:
        params["recipient"] = [recipient]

    if attachments:
        params["attachment"] = attachments

    request_id = "reply-id"
    if wants_answer_callback:
        request_id = str(uuid.uuid4())
        PENDING_REPLIES[request_id] = wants_answer_callback

    rpc_request: dict[str, Any] = {
        "jsonrpc": "2.0",
        "method": "send",
        "params": params,
        "id": request_id
    }
    logger.debug(f"Sending message: {rpc_request}")

    # Write to signal-cli stdin
    try:
        assert proc.stdin is not None
        proc.stdin.write(json.dumps(rpc_request).encode('utf-8') + b"\n")
        await proc.stdin.drain()
    except Exception as e:
        logger.error(f"Failed to send message: {e}")


async def get_group_info(group_id: str, callback: Callable[[dict[str, Any]], Awaitable[None]]) -> None:
    """
    Requests group information from signal-cli and calls the callback with the response.
    """
    global signal_process
    if not signal_process:
        logger.error("Signal process not initialized.")
        return

    proc: Process = signal_process
    params: dict[str, Any] = {
        "groupId": group_id
    }

    request_id = str(uuid.uuid4())

    PENDING_REPLIES[request_id] = callback

    rpc_request: dict[str, Any] = {
        "jsonrpc": "2.0",
        "method": "listGroups",
        "params": params,
        "id": request_id
    }

    # Write to signal-cli stdin
    try:
        assert proc.stdin is not None
        proc.stdin.write(json.dumps(rpc_request).encode('utf-8') + b"\n")
        await proc.stdin.drain()
    except Exception as e:
        logger.error(f"Failed to send message: {e}")
