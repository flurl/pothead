"""
This plugin demonstrates basic functionalities of the Pothead plugin system.
It includes:
- Registering actions by echoing back messages received from Signal (both data and sync messages).
- Registering commands by responding to a simple 'ping' command.
- Registering event handlers by sending messages to the superuser on startup and shutdown events.
- Consuming other plugin's services by utilizing the 'cron' service to schedule a periodic 'heartbeat' task.
"""

import logging
from typing import Any, Callable, cast

from config import settings
from datatypes import ChatMessage, Event
from messaging import send_signal_direct_message, send_signal_message
from plugin_manager import register_action, register_command, get_service, register_event_handler, get_plugin_settings


logger: logging.Logger = logging.getLogger(__name__)

plugin_id: str = "echo"

from plugins.echo.config import PluginSettings  # nopep8
plugin_settings: PluginSettings = cast(
    PluginSettings, get_plugin_settings(plugin_id))


async def log_echo_response(response_data: dict[str, Any]) -> None:
    """Callback function to log the response of the sent echo message."""
    logger.info(f"Received confirmation for echo: {response_data}")


@register_action(
    plugin_id,
    name="Echo Data Message",
    jsonpath="$.params.envelope.dataMessage",
)
@register_action(
    plugin_id,
    name="Echo Sync Message",
    jsonpath="$.params.envelope.syncMessage.sentMessage",
)
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
            source="Echo", destination=incoming.source, text=f"{plugin_settings.echo_prefix} {incoming.text}", group_id=incoming.group_id)
        await send_signal_message(outgoing, wants_answer_callback=log_echo_response)
    return True


@register_command(plugin_id, "ping", "Responds with Pong!")
async def cmd_ping(chat_id: str, params: list[str], prompt: str | None) -> tuple[str, list[str]]:
    """Responds with Pong!"""
    return "Pong!", []


@register_command(plugin_id, "echo", "Responds with the prompt!")
async def cmd_echo(chat_id: str, params: list[str], prompt: str | None) -> tuple[str, list[str]]:
    """Responds with the prompt!"""
    return prompt if prompt else "", []


@register_event_handler(plugin_id, Event.POST_STARTUP)
async def on_startup() -> None:
    """Sends a startup message to the superuser."""
    await send_signal_direct_message(
        message="Hello from pothead!",
        recipient=settings.superuser
    )


@register_event_handler(plugin_id, Event.PRE_SHUTDOWN)
async def on_shutdown() -> None:
    """Sends a shutdown message to the superuser."""
    await send_signal_direct_message(
        message="Goodbye from pothead!",
        recipient=settings.superuser
    )


async def heartbeat() -> None:
    """A simple periodic task to demonstrate cron service usage."""
    logger.info("Echo plugin heartbeat!")


def initialize() -> None:
    """Initializes the plugin and schedules the heartbeat."""
    logger.info("Initializing echo plugin and scheduling heartbeat.")
    register_cron_job: Callable[..., Any] | None = get_service(
        "register_cron_job")
    if register_cron_job:
        # Run every minute
        register_cron_job(heartbeat, interval=1)
        logger.info("Successfully scheduled echo heartbeat.")
    else:
        logger.warning(
            "Could not schedule heartbeat, 'register_cron_job' service not found.")
