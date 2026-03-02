import dataclasses
import json
import logging
import os
from typing import Any, cast

from datatypes import ChatMessage, DeleteMessage, EditMessage, Event, SignalMessage
from plugin_manager import register_command, register_event_handler
from utils import get_safe_chat_dir, save_attachment

logger: logging.Logger = logging.getLogger(__name__)

plugin_id: str = "archiver"

# Directory to store archives. relative to plugin root.
ARCHIVES_DIR: str = os.path.join(os.path.dirname(__file__), "archives")
ENABLED_CHATS_FILE: str = os.path.join(
    os.path.dirname(__file__), "enabled_chats.json"
)


def load_enabled_chats() -> set[str]:
    """Loads the list of enabled chats from the JSON file."""
    if os.path.exists(ENABLED_CHATS_FILE):
        try:
            with open(ENABLED_CHATS_FILE, "r") as f:
                data: set[str] = set(json.load(f))
                return set(data)
        except Exception as e:
            logger.error(f"Failed to load enabled chats: {e}")
    return set()


def save_enabled_chats(chats: set[str]) -> None:
    """Saves the list of enabled chats to the JSON file."""
    try:
        with open(ENABLED_CHATS_FILE, "w") as f:
            json.dump(list(chats), f, indent=2)
    except Exception as e:
        logger.error(f"Failed to save enabled chats: {e}")


enabled_chats: set[str] = load_enabled_chats()


@register_command(plugin_id, "enablearchive", "Enables archiving for the current chat.")
async def cmd_enable_archive(chat_id: str, params: list[str], prompt: str | None) -> tuple[str, list[str]]:
    """Enables archiving for the current chat."""
    if chat_id not in enabled_chats:
        enabled_chats.add(chat_id)
        save_enabled_chats(enabled_chats)
        return f"📂 Archiving enabled for chat {chat_id}.", []
    return f"ℹ️ Archiving is already enabled for chat {chat_id}.", []


@register_command(plugin_id, "disablearchive", "Disables archiving for the current chat.")
async def cmd_disable_archive(chat_id: str, params: list[str], prompt: str | None) -> tuple[str, list[str]]:
    """Disables archiving for the current chat."""
    if chat_id in enabled_chats:
        enabled_chats.remove(chat_id)
        save_enabled_chats(enabled_chats)
        return f"🛑 Archiving disabled for chat {chat_id}.", []
    return f"ℹ️ Archiving was not enabled for chat {chat_id}.", []


@register_event_handler(plugin_id, Event.CHAT_MESSAGE_RECEIVED)
@register_event_handler(plugin_id, Event.CHAT_MESSAGE_EDITED)
@register_event_handler(plugin_id, Event.CHAT_MESSAGE_DELETED)
async def on_chat_event(msg: SignalMessage) -> None:
    """
    Archives chat events (received, edited, deleted messages) if archiving is enabled for the chat.
    """
    # We only care about messages that have a chat context.
    if not isinstance(msg, (ChatMessage, EditMessage, DeleteMessage)):
        logger.debug(f"Archiver skipping message of type {type(msg)}")
        return

    # All these types are subclasses of ChatMessage (or ChatMessage itself), which has chat_id
    chat_msg: ChatMessage = cast(ChatMessage, msg)
    chat_id: str = chat_msg.chat_id

    if chat_id not in enabled_chats:
        return

    try:
        chat_dir: str = get_safe_chat_dir(ARCHIVES_DIR, chat_id)
        os.makedirs(chat_dir, exist_ok=True)

        # Convert dataclass to dict for JSON serialization.
        msg_dict: dict[str, Any] = dataclasses.asdict(msg)

        # Append message to messages.jsonl
        messages_file: str = os.path.join(chat_dir, "messages.jsonl")
        with open(messages_file, "a", encoding="utf-8") as f:
            # Manually convert enum to value for serialization
            msg_dict["type"] = msg.type.value
            f.write(json.dumps(msg_dict) + "\n")

        # Handle attachments for ChatMessage and EditMessage
        if (not isinstance(msg, (DeleteMessage))) and msg.attachments:
            att_dir: str = os.path.join(chat_dir, "attachments")
            os.makedirs(att_dir, exist_ok=True)

            for att in msg.attachments:
                # Construct destination filename
                # Prefix with timestamp to group by message approximately
                # Include attachment ID to be unique
                safe_filename: str = (
                    os.path.basename(
                        att.filename) if att.filename else att.id
                )
                dest_filename: str = f"{msg.timestamp}_{att.id}_{safe_filename}"
                save_attachment(att, att_dir, dest_filename)

    except Exception as e:
        logger.error(f"Error archiving message for {chat_id}: {e}")
