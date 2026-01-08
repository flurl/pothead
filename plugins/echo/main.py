import logging
from typing import Any

from datatypes import ChatMessage
from messaging import send_signal_message
from plugin_manager import register_action, register_command

logger: logging.Logger = logging.getLogger(__name__)


async def log_echo_response(response_data: dict[str, Any]) -> None:
    """Callback function to log the response of the sent echo message."""
    logger.info(f"Received confirmation for echo: {response_data}")


async def echo_handler(data: dict[str, Any]) -> bool:
    """
    Handles echoing a message back to the sender from either a dataMessage or a syncMessage.
    """
    incoming: ChatMessage | None = ChatMessage.from_json(data)
    if not incoming:
        return False

    if not incoming.text:
        return False

    if not incoming.text.startswith("!"):
        logger.info(
            f"Echoing message from {incoming.source} in group {incoming.group_id}")
        outgoing: ChatMessage = ChatMessage(
            source="Echo", destination=incoming.source, text=f"Echo: {incoming.text}", group_id=incoming.group_id)
        await send_signal_message(outgoing, wants_answer_callback=log_echo_response)
    return True


async def cmd_ping(chat_id: str, params: list[str], prompt: str | None) -> tuple[str, list[str]]:
    """Responds with Pong!"""
    return "Pong!", []


# Register actions for both data messages and sync messages
register_action(
    "echo",
    name="Echo Data Message",
    jsonpath="$.params.envelope.dataMessage",
    handler=echo_handler
)
register_action(
    "echo",
    name="Echo Sync Message",
    jsonpath="$.params.envelope.syncMessage.sentMessage",
    handler=echo_handler
)

register_command("echo", "ping", cmd_ping, "Responds with Pong!")
