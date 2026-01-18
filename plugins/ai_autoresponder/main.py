"""
This plugin demonstrates basic functionalities of the Pothead plugin system.
It includes:
- Registering actions by echoing back messages received from Signal (both data and sync messages).
- Registering commands by responding to a simple 'ping' command.
- Registering event handlers by sending messages to the superuser on startup and shutdown events.
- Consuming other plugin's services by utilizing the 'cron' service to schedule a periodic 'heartbeat' task.
"""

import logging
import os
import time
from typing import Any, Callable, cast

from datatypes import ChatMessage, Event
from plugin_manager import register_command, get_service, register_event_handler, get_plugin_settings
from config import settings


logger: logging.Logger = logging.getLogger(__name__)

plugin_id: str = "ai_autoresponder"

from plugins.ai_autoresponder.config import PluginSettings  # nopep8
plugin_settings: PluginSettings = cast(
    PluginSettings, get_plugin_settings(plugin_id))

send_to_ai: Callable[..., Any] | None = None
auto_chat_ids: list[str] = plugin_settings.auto_chat_ids
ignore_time: int | None = None

AUTO_CHAT_IDS_FILE: str = os.path.join(
    os.path.dirname(__file__), "auto_chat_ids.txt")


def save_auto_chat_ids() -> None:
    """Persists the list of auto-enabled chat IDs to disk."""
    try:
        with open(AUTO_CHAT_IDS_FILE, "w") as f:
            for cid in auto_chat_ids:
                f.write(f"{cid}\n")
    except Exception as e:
        logger.error(f"Failed to save auto_chat_ids: {e}")


@register_command(plugin_id, "autoenable", "Enables autoresponder for chat!")
async def cmd_autoenable(chat_id: str, params: list[str], prompt: str | None) -> tuple[str, list[str]]:
    if chat_id not in auto_chat_ids:
        auto_chat_ids.append(chat_id)
        save_auto_chat_ids()
        return f"✅ Autoresponder enabled for chat ID: {chat_id}", []
    return f"ℹ️ Autoresponder already enabled for chat ID: {chat_id}", []


@register_command(plugin_id, "autodisable", "Disables autoresponder for chat!")
async def cmd_autodisable(chat_id: str, params: list[str], prompt: str | None) -> tuple[str, list[str]]:
    if chat_id in auto_chat_ids:
        auto_chat_ids.remove(chat_id)
        save_auto_chat_ids()
        return f"❌ Autoresponder disabled for chat ID: {chat_id}", []
    return f"ℹ️ Autoresponder not enabled for chat ID: {chat_id}", []


@register_event_handler(plugin_id, Event.CHAT_MESSAGE_RECEIVED)
async def on_chat_message_received(msg: ChatMessage) -> None:
    global send_to_ai
    global ignore_time
    # check if the message's chat_id is in auto_chat_ids. If found forward the message to send_to_ai
    if msg.chat_id in auto_chat_ids:
        # Check if the message is a command (starts with !TRIGGER#)
        text: str = msg.text or ""
        clean_text: str = text.strip()
        for tw in sorted(settings.trigger_words, key=len, reverse=True):
            if clean_text.upper().startswith(tw.upper()):
                remaining: str = clean_text[len(tw):].strip()
                if remaining.startswith("#"):
                    return

        # check if message source is the same as the bot's account.
        # If so ignore further messages for wait_after_message_from_self seconds
        if msg.source == settings.signal_account:
            ignore_time = int(time.time())
            return
        elif int(time.time() - (ignore_time or 0)) > plugin_settings.wait_after_message_from_self:
            ignore_time = None
        else:
            return

        if send_to_ai:
            logger.info(
                f"Autoresponder: Forwarding message from {msg.chat_id} to AI.")
            await send_to_ai(msg)
        else:
            logger.warning(
                "Autoresponder: send_to_ai service not available.")


def initialize() -> None:
    """Initializes the plugin"""
    global send_to_ai
    logger.info(f"Initializing {plugin_id} plugin")
    # read the file auto_chat_ids.txt and extend the auto_chat_ids list with the ids found in that file
    if os.path.exists(AUTO_CHAT_IDS_FILE):
        with open(AUTO_CHAT_IDS_FILE, "r") as f:
            for line in f:
                chat_id: str = line.strip()
                if chat_id and chat_id not in auto_chat_ids:
                    auto_chat_ids.append(chat_id)

    send_to_ai = get_service("send_to_ai")
    if send_to_ai:
        logger.info("Successfully initialized send_to_ai service")
    else:
        logger.warning(
            "Could not initialize send_to_ai service.")
