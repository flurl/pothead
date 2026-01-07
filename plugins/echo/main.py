import logging
from typing import Any

from messaging import send_signal_direct_message, send_signal_group_message
from plugin_manager import register_action, register_command

logger: logging.Logger = logging.getLogger(__name__)


async def log_echo_response(response_data: dict[str, Any]) -> None:
    """Callback function to log the response of the sent echo message."""
    logger.info(f"Received confirmation for echo: {response_data}")


async def echo_handler(data: dict[str, Any]) -> bool:
    """
    Handles echoing a message back to the sender from either a dataMessage or a syncMessage.
    """
    envelope = data.get("params", {}).get("envelope", {})
    source = envelope.get("source")

    msg_payload = None
    if "dataMessage" in envelope:
        msg_payload = envelope.get("dataMessage")
    elif "syncMessage" in envelope:
        msg_payload = envelope.get("syncMessage", {}).get("sentMessage")

    if not msg_payload:
        return False

    message_body = msg_payload.get("message")
    group_id = msg_payload.get("groupInfo", {}).get("groupId")

    # Avoid echoing commands or empty messages
    if source and message_body and not message_body.startswith("!"):
        logger.info(f"Echoing message from {source} in group {group_id}")
        if group_id:
            await send_signal_group_message(
                group_id,
                f"Echo: {message_body}",
                wants_answer_callback=log_echo_response
            )
        else:
            await send_signal_direct_message(
                f"Echo: {message_body}",
                source,
                wants_answer_callback=log_echo_response
            )
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
