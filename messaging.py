
import json
import logging
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from asyncio.subprocess import Process
from config import settings
from plugin_manager import PENDING_REPLIES

logger: logging.Logger = logging.getLogger(__name__)

signal_process: Process | None = None


def set_signal_process(proc: Process) -> None:
    global signal_process
    signal_process = proc


async def send_signal_message(
    recipient: str,
    message: str,
    group_id: str | None = None,
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
    params: dict[str, Any] = {
        "account": settings.signal_account,
        "message": message
    }

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

    # Write to signal-cli stdin
    try:
        assert proc.stdin is not None
        proc.stdin.write(json.dumps(rpc_request).encode('utf-8') + b"\n")
        await proc.stdin.drain()
    except Exception as e:
        logger.error(f"Failed to send message: {e}")
