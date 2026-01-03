import logging
from typing import Any
from asyncio.subprocess import Process

from messaging import send_signal_message
from plugin_manager import register_action

logger = logging.getLogger(__name__)


async def log_echo_response(response_data: dict[str, Any]) -> None:
    """Callback function to log the response of the sent echo message."""
    logger.info(f"Received confirmation for echo: {response_data}")


async def echo_handler(proc: Process, data: dict[str, Any]) -> None:
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
        return

    message_body = msg_payload.get("message")
    group_id = msg_payload.get("groupInfo", {}).get("groupId")

    # Avoid echoing commands or empty messages
    if source and message_body and not message_body.startswith("!"):
        logger.info(f"Echoing message from {source} in group {group_id}")
        await send_signal_message(
            proc,
            source,
            f"Echo: {message_body}",
            group_id,
            wants_answer_callback=log_echo_response
        )

# Register actions for both data messages and sync messages
register_action(
    name="Echo Data Message",
    jsonpath="$.params.envelope.dataMessage",
    handler=echo_handler
)
register_action(
    name="Echo Sync Message",
    jsonpath="$.params.envelope.syncMessage.sentMessage",
    handler=echo_handler
)