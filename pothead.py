from config import settings
import asyncio
from asyncio.subprocess import Process
from collections import deque
from dataclasses import dataclass, field
import json
import logging

import sys
from typing import Any, Awaitable, Callable

import jsonpath_ng

from state import CHAT_HISTORY
from ai import AI_PROVIDER
from commands import COMMANDS
from datatypes import Attachment, ChatMessage
from utils import check_permission


# --- CONFIGURATION ---
# Configure logging
logging.basicConfig(
    level=settings.log_level.upper(),
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger: logging.Logger = logging.getLogger(__name__)


@dataclass
class Action:
    name: str
    jsonpath: str
    handler: Callable[[Process, dict[str, Any]], Awaitable[None]]
    _compiled_path: Any = field(init=False)

    def __post_init__(self) -> None:
        self._compiled_path = jsonpath_ng.parse(self.jsonpath)  # type: ignore

    def matches(self, data: dict[str, Any]) -> bool:
        return bool(self._compiled_path.find(data))


async def execute_command(chat_id: str, sender: str, command: str, params: list[str], prompt: str | None = None) -> tuple[str, list[str]]:
    command = command.lower()
    """Executes the parsed command."""
    if not check_permission(chat_id, sender, command):
        return f"⛔ Permission denied for command: {command}", []

    for cmd in COMMANDS:
        print(f"Checking command: {cmd.name} == {command}")
        if cmd.name == command:
            return await cmd.handler(chat_id, params, prompt)
    return f"❓ Unknown command: {command}", []


def update_chat_history(chat_id: str, sender: str, message: str | None, attachments: list[Attachment] | None = None) -> None:
    if attachments is None:
        attachments = []
    if chat_id not in CHAT_HISTORY:
        CHAT_HISTORY[chat_id] = deque[ChatMessage](
            maxlen=settings.history_max_length)
    CHAT_HISTORY[chat_id].append(ChatMessage(
        sender=sender, text=message, attachments=attachments))
    logger.debug(f"Chat history for {chat_id}: {CHAT_HISTORY[chat_id]}")
    for line in CHAT_HISTORY[chat_id]:
        logger.debug(line)


async def send_signal_message(proc: Process, recipient: str, message: str, group_id: str | None = None, attachments: list[str] | None = None) -> None:
    """
    Sends a message back via signal-cli JSON-RPC.
    Supports direct messages (recipient) and group messages (group_id).
    """
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

    rpc_request: dict[str, Any] = {
        "jsonrpc": "2.0",
        "method": "send",
        "params": params,
        "id": "reply-id"
    }

    # Write to signal-cli stdin
    try:
        assert proc.stdin is not None
        proc.stdin.write(json.dumps(rpc_request).encode('utf-8') + b"\n")
        await proc.stdin.drain()
    except Exception as e:
        logger.error(f"Failed to send message: {e}")


async def process_message(proc: Process, data: dict[str, Any]) -> None:
    """Default action handler for incoming messages."""
    params = data.get("params", {})
    envelope = params.get("envelope", {})

    # 1. Extract source
    source: str = envelope.get("source")

    # 2. Extract Message Body and Context (Group vs Direct)
    # We need to look in two places: dataMessage (incoming) and syncMessage (sent from other devices)
    message_body: str | None = None
    group_id: str | None = None
    quote: str | None = None
    attachments: list[Attachment] = []

    # Determine message payload (dataMessage or syncMessage -> sentMessage)
    msg_payload: dict[str, Any] | None = None
    if "dataMessage" in envelope:
        msg_payload = envelope.get("dataMessage")
    elif "syncMessage" in envelope:
        msg_payload = envelope.get("syncMessage", {}).get("sentMessage")

    if msg_payload:
        message_body = msg_payload.get("message")
        if "groupInfo" in msg_payload:
            group_id = msg_payload["groupInfo"].get("groupId")
        if "quote" in msg_payload:
            quote = msg_payload["quote"].get("text")
        if "attachments" in msg_payload:
            for att in msg_payload["attachments"]:
                attachments.append(Attachment(
                    content_type=att.get("contentType", "unknown"),
                    id=att.get("id", ""),
                    size=att.get("size", 0),
                    filename=att.get("filename"),
                    width=att.get("width"),
                    height=att.get("height"),
                    caption=att.get("caption")
                ))

    # If no text found, ignore (e.g., receipts, typing indicators)
    if not message_body and not attachments:
        return

    chat_id: str = group_id if group_id else source
    update_chat_history(chat_id, source, message_body, attachments)

    # 3. Check Prefixes (!pothead or !pot or !ph)
    clean_msg: str = message_body.strip() if message_body else ""
    prompt: str | None = None
    command: str | None = None
    command_params: list[str] = []

    settings.trigger_words.sort(key=len, reverse=True)
    for tw in settings.trigger_words:
        if clean_msg.startswith(tw):
            content: str = clean_msg[len(tw):].strip()
            if content.startswith("#"):
                # Parse command
                # Syntax: !TRIGGERWORD#COMMAND,PARAM1,PARAM2,... PROMPT
                cmd_content: str = content[1:]
                cmd_part: str
                prompt_part: str
                if " " in cmd_content:
                    cmd_part, prompt_part = cmd_content.split(" ", 1)
                    prompt = prompt_part.strip()
                else:
                    cmd_part: str = cmd_content
                    prompt = None

                parts: list[str] = cmd_part.split(',')
                command = parts[0].strip()
                if len(parts) > 1:
                    command_params = [p.strip() for p in parts[1:]]
            else:
                prompt = content
            break

    # nothing to do for AI
    if prompt is None and command is None:
        return

    if quote is not None:
        prompt = f"{prompt}\n\n{quote}"

    # 4. Process
    if command is not None:
        logger.info(
            f"Processing command from {source} (Group: {group_id}): {command} {command_params}")
        response_text: str | None = None
        response_attachments: list[str] = []
        response_text, response_attachments = await execute_command(chat_id, source, command, command_params, prompt)
        await send_signal_message(proc, source, response_text, group_id, response_attachments)
        logger.info(f"Sent response to {source}")

    elif prompt is not None:
        logger.info(
            f"Processing request from {source} (Group: {group_id}): {prompt}")

        if not prompt:
            response_text = "🤖 Beep Boop. Please provide a prompt."
        else:
            response_text: str | None = await AI_PROVIDER.get_response(chat_id, prompt)

        # 5. Send Response
        # If group_id exists, we reply to the group. If not, we reply to the source.
        if response_text is None:
            response_text = "🤖 Beep Boop. Something went wrong."

        update_chat_history(chat_id, "Assistant", response_text)

        await send_signal_message(proc, source, response_text, group_id)
        logger.info(f"Sent response to {source}")


ACTIONS: list[Action] = [
    Action(
        name="Handle Data Message",
        jsonpath="$.params.envelope.dataMessage",
        handler=process_message
    ),
    Action(
        name="Handle Sync Message",
        jsonpath="$.params.envelope.syncMessage",
        handler=process_message
    )
]


async def process_incoming_line(proc: Process, line: str) -> None:
    """Parses a line of JSON from signal-cli."""
    try:
        data: Any = json.loads(line)
    except json.JSONDecodeError:
        return

    for action in ACTIONS:
        if action.matches(data):
            await action.handler(proc, data)


async def main() -> None:
    # Start signal-cli in jsonRpc mode
    # -a specifies the account sending/receiving
    cmd: list[str] = [settings.signal_cli_path, "-a",
                      settings.signal_account, "jsonRpc"]  # type: ignore

    logger.info(f"Starting signal-cli: {' '.join(cmd)}")

    proc: Process = await asyncio.create_subprocess_exec(
        *cmd,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=sys.stderr  # Print errors to console directly
    )

    logger.info("Listening for messages...")

    try:
        while True:
            assert proc.stdout is not None
            # Read line by line from signal-cli stdout
            line: bytes = await proc.stdout.readline()
            logger.debug(f"received: {line}")
            if not line:
                break

            decoded_line: str = line.decode('utf-8').strip()
            if decoded_line:
                # Process each line asynchronously so we don't block reading
                asyncio.create_task(process_incoming_line(proc, decoded_line))

    except asyncio.CancelledError:
        pass
    finally:
        if proc.returncode is None:
            proc.terminate()
            await proc.wait()

if __name__ == "__main__":
    asyncio.run(main())
