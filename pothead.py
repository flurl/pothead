from collections.abc import Awaitable, Callable
from config import settings
import asyncio
from asyncio.subprocess import Process
import json
import logging
import sys
from typing import Any

from jsonpath_ng.jsonpath import DatumInContext

from commands import COMMANDS
from datatypes import Attachment, Action, Priority
from messaging import send_signal_message, set_signal_process
from utils import check_permission, update_chat_history
from plugin_manager import PENDING_REPLIES, PLUGIN_ACTIONS, load_plugins, PLUGIN_COMMANDS


# --- CONFIGURATION ---
# Configure logging
logging.basicConfig(
    level=settings.log_level.upper(),
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger: logging.Logger = logging.getLogger(__name__)


async def execute_command(chat_id: str, sender: str, command: str, params: list[str], prompt: str | None = None) -> tuple[str, list[str]]:
    command = command.lower()
    """Executes the parsed command."""
    if not check_permission(chat_id, sender, command):
        return f"⛔ Permission denied for command: {command}", []

    for cmd in COMMANDS:
        if cmd.name == command:
            return await cmd.handler(chat_id, params, prompt)
    return f"❓ Unknown command: {command}", []


async def handle_command(data: dict[str, Any]) -> bool:
    """Handles incoming commands."""
    params: dict[str, Any] = data.get("params", {})
    envelope: dict[str, Any] = params.get("envelope", {})
    source: str | None = envelope.get("source")
    if source is None:
        logger.error("No source found in envelope.")
        return False

    message_body: str | None = None
    group_id: str | None = None
    quote: str | None = None
    attachments: list[Attachment] = []

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

    if not message_body:
        return False

    chat_id: str = group_id if group_id else source
    clean_msg: str = message_body.strip()

    settings.trigger_words.sort(key=len, reverse=True)
    for tw in settings.trigger_words:
        if clean_msg.startswith(tw):
            content: str = clean_msg[len(tw):].strip()
            if content.startswith("#"):
                update_chat_history(chat_id, source, message_body, attachments)

                cmd_content: str = content[1:]
                if " " in cmd_content:
                    cmd_part: str
                    prompt_part: str
                    cmd_part, prompt_part = cmd_content.split(" ", 1)
                    prompt: str | None = prompt_part.strip()
                else:
                    cmd_part: str = cmd_content
                    prompt = None

                parts: list[str] = cmd_part.split(',')
                command: str = parts[0].strip()
                command_params: list[str] = [p.strip()
                                             for p in parts[1:]] if len(parts) > 1 else []

                if quote is not None:
                    prompt = f"{prompt}\n\n{quote}" if prompt else quote

                logger.info(
                    f"Processing command from {source} (Group: {group_id}): {command} {command_params}")
                response_text: str | None = None
                response_attachments: list[str] = []
                response_text, response_attachments = await execute_command(chat_id, source, command, command_params, prompt)
                await send_signal_message(source, response_text, group_id, response_attachments)
                logger.info(f"Sent response to {source}")
                return True

    return False


def command_filter(match: DatumInContext) -> bool:
    if str(match.path) == "message" and match.value is not None:  # type: ignore
        msg: str = match.value  # type: ignore
    else:
        return False
    return msg.strip().startswith(tuple(w+"#" for w in settings.trigger_words))  # type: ignore


# dataMessage are usual messages from signal accounts
# syncMessage are messages sent from me on other devices (or received there while PH was offline)
# the order is important as we want to first check for !TRIGGER#CMD and then for just !TRIGGER
ACTIONS: list[Action] = [
    Action(
        name="Handle Command in Data Message",
        jsonpath="$.params.envelope.dataMessage.message",
        filter=command_filter,
        handler=handle_command,
        priority=Priority.SYS,
        origin="sys"
    ),
    Action(
        name="Handle Command in Sync Message",
        jsonpath="$.params.envelope.syncMessage.sentMessage.message",
        filter=command_filter,
        handler=handle_command,
        priority=Priority.SYS,
        origin="sys"
    )
]


async def process_incoming_line(line: str) -> None:
    """Parses a line of JSON from signal-cli."""
    try:
        data: Any = json.loads(line)
    except json.JSONDecodeError:
        return

    request_id: str | None = data.get("id")
    if request_id and request_id in PENDING_REPLIES:
        callback: Callable[[dict[str, Any]], Awaitable[None]
                           ] = PENDING_REPLIES.pop(request_id)
        await callback(data)
        return

    for action in ACTIONS:
        if action.matches(data):
            message_handeled: bool = await action.handler(data)
            if message_handeled:
                return


async def main() -> None:
    # Load plugins before starting the main loop
    load_plugins()
    ACTIONS.extend(PLUGIN_ACTIONS)
    COMMANDS.extend(PLUGIN_COMMANDS)
    # Sort actions by priority (SYS -> LOW)
    ACTIONS.sort(key=lambda a: a.priority.value, reverse=True)
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

    set_signal_process(proc)

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
                asyncio.create_task(process_incoming_line(decoded_line))

    except asyncio.CancelledError:
        pass
    finally:
        if proc.returncode is None:
            proc.terminate()
            await proc.wait()

if __name__ == "__main__":
    asyncio.run(main())
