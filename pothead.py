
"""
The main entry point for the Pothead application.

This module orchestrates the core lifecycle of the bot, including:
- Initializing configuration and logging.
- Loading and initializing plugins via `plugin_manager`.
- Managing the `signal-cli` subprocess for sending and receiving messages.
- Processing incoming JSON-RPC messages from `signal-cli`.
- Dispatching messages to registered Actions (both system-level and plugin-level).
- Handling user commands and executing them.
- Managing the main event loop and system events (e.g., startup, shutdown, timer).

Key Components:
- `main()`: The async entry point that sets up the environment and starts the processing loop.
- `process_incoming_line()`: Parses raw output from `signal-cli` and routes it.
- `handle_command()`: A system action that interprets and executes user commands starting with trigger words.
- `timer_loop()`: A background task that fires the `Event.TIMER` event periodically.

Usage:
    Run this module directly to start the bot:
    $ python pothead.py
"""

from collections.abc import Awaitable, Callable
from config import settings
import asyncio
from asyncio.subprocess import Process
import json
import logging
import sys
import time
from typing import Any, cast

from jsonpath_ng.jsonpath import DatumInContext

from commands import COMMANDS
from datatypes import Action, ChatMessage, MessageQuote, MessageType, Priority, Event, SignalMessage
from messaging import set_signal_process, send_signal_message
from utils import check_permission, update_chat_history
from plugin_manager import (
    PENDING_REPLIES,
    PLUGIN_ACTIONS,
    load_plugins,
    PLUGIN_COMMANDS,
    EVENT_HANDLERS,
)


# --- CONFIGURATION ---
# Configure logging
logging.basicConfig(
    level=settings.log_level.upper(),
    format="%(asctime)s [%(levelname)s] %(filename)s:%(lineno)d %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger: logging.Logger = logging.getLogger(__name__)


async def fire_event(event: Event, *args: Any, **kwargs: Any) -> None:
    """Fires an event and runs all registered handlers."""
    logger.info(f"Firing event: {event}")
    if event in EVENT_HANDLERS:
        for handler in EVENT_HANDLERS[event]:
            try:
                await handler(*args, **kwargs)
            except Exception:
                logger.exception(f"Error in event handler for {event}")


async def timer_loop() -> None:
    """Emits a timer event every minute."""
    while True:
        await asyncio.sleep(60)
        await fire_event(Event.TIMER)


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
    msg: SignalMessage | None = SignalMessage.from_json(data)
    if msg and msg.type == MessageType.CHAT:
        msg = cast(ChatMessage, msg)
    else:
        return False

    chat_id: str = msg.chat_id

    if not msg.text:
        return False
    clean_msg: str = msg.text.strip()

    quote: MessageQuote | None = msg.quote

    settings.trigger_words.sort(key=len, reverse=True)
    for tw in settings.trigger_words:
        if clean_msg.startswith(tw):
            content: str = clean_msg[len(tw):].strip()
            if content.startswith("#"):
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
                    prompt = f"{prompt}\n\n{quote.text}" if prompt else quote.text

                logger.info(
                    f"Processing command from {msg.source}): {command} {command_params}")
                response_text: str | None = None
                response_attachments: list[str] = []
                response_text, response_attachments = await execute_command(chat_id, msg.source, command, command_params, prompt)

                response: ChatMessage = ChatMessage(
                    source="Assistant", destination=chat_id, text=response_text, group_id=msg.group_id, type=MessageType.CHAT)

                await send_signal_message(response, attachments=response_attachments)
                update_chat_history(response)
                logger.info(f"Sent response to {msg.source}")
                return True

    return False


async def handle_incomming_message(data: dict[str, Any]) -> bool:
    msg: SignalMessage | None = SignalMessage.from_json(data)
    if msg:
        # Ignore messages older than ignore_messages_older_than secs
        if (time.time() * 1000) - msg.timestamp > settings.ignore_messages_older_than * 1000:
            logger.debug(
                f"Ignoring old message from {msg.source} (timestamp: {msg.timestamp})")
            return True

        if msg.type == MessageType.CHAT:
            update_chat_history(msg)
            await fire_event(Event.CHAT_MESSAGE_RECEIVED, msg)
        elif msg.type == MessageType.EDIT:
            print(msg)
            update_chat_history(msg)
            await fire_event(Event.CHAT_MESSAGE_EDITED, msg)
        elif msg.type == MessageType.DELETE:
            update_chat_history(msg)
            await fire_event(Event.CHAT_MESSAGE_DELETED, msg)

    # always return false so that the message is further processed
    return False


def command_filter(match: DatumInContext) -> bool:
    if str(match.path) == "message" and match.value is not None:  # type: ignore
        msg: str = match.value  # type: ignore
    else:
        return False
    return msg.strip().upper().startswith(tuple((w+"#").upper() for w in settings.trigger_words))  # type: ignore


# dataMessage are usual messages from signal accounts
# syncMessage are messages sent from me on other devices (or received there while PH was offline)
# the order is important as we want to first check for !TRIGGER#CMD and then for just !TRIGGER
ACTIONS: list[Action] = [
    Action(
        name="Handle incomming message",
        jsonpath="$.params.envelope",
        filter=None,
        handler=handle_incomming_message,
        priority=Priority.SYS,
        origin="sys"
    ),
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
        stderr=sys.stderr,  # Print errors to console directly
        start_new_session=True
    )

    set_signal_process(proc)
    timer_task: asyncio.Task[None] = asyncio.create_task(timer_loop())
    await fire_event(Event.POST_STARTUP)
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
        timer_task.cancel()
        await fire_event(Event.PRE_SHUTDOWN)
        if proc.returncode is None:
            proc.terminate()
            await proc.wait()

if __name__ == "__main__":
    asyncio.run(main())
