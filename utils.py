
"""
This module provides utility functions for file system operations, permission checks,
and state management.

It includes helpers for:
- Determining safe file paths for chat storage.
- Loading and saving permissions (users and groups).
- Checking if a user has permission to execute a command.
- Managing chat history updates.
- Saving attachments to disk.
"""

import hashlib
import json
import logging
import os
import shutil
from typing import Any

from config import settings

from collections import deque
from datatypes import Attachment, ChatMessage, Permissions
from state import CHAT_HISTORY

logger: logging.Logger = logging.getLogger(__name__)


def get_safe_chat_dir(base_path: str, chat_id: str) -> str:
    hashed_id = hashlib.sha256(chat_id.encode("utf-8")).hexdigest()
    return os.path.join(base_path, hashed_id)


def get_local_file_store_path(chat_id: str) -> str:
    return get_safe_chat_dir(settings.file_store_path, chat_id)


def get_local_files(chat_id: str) -> list[str]:
    chat_dir: str = get_local_file_store_path(chat_id)
    if os.path.isdir(chat_dir):
        return sorted([f for f in os.listdir(chat_dir) if os.path.isfile(os.path.join(chat_dir, f))])
    return []


def get_permissions_file(chat_id: str) -> str:
    store_path: str = settings.permissions_store_path
    chat_dir: str = get_safe_chat_dir(store_path, chat_id)
    os.makedirs(chat_dir, exist_ok=True)
    return os.path.join(chat_dir, "permissions.json")


def load_permissions(chat_id: str) -> Permissions:
    filepath: str = get_permissions_file(chat_id)
    perms: Permissions = {"users": {}, "groups": {}}
    if os.path.exists(filepath):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                perms = json.load(f)
        except Exception as e:
            logger.error(f"Failed to load permissions for {chat_id}: {e}")

    if "groups" not in perms:
        perms["groups"] = {}
    if "ALL" not in perms["groups"]:
        perms["groups"]["ALL"] = {"members": [], "permissions": []}
    return perms


def save_permissions(chat_id: str, perms: dict[str, Any]) -> None:
    filepath: str = get_permissions_file(chat_id)
    try:
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(perms, f, indent=2)
    except Exception as e:
        logger.error(f"Failed to save permissions for {chat_id}: {e}")


def check_permission(chat_id: str, sender: str, command: str) -> bool:
    superuser: str = settings.superuser
    if superuser and sender == superuser:
        return True

    perms: dict[str, Any] = load_permissions(chat_id)

    # 1. Direct user permission
    if command in perms.get("users", {}).get(sender, []):
        return True

    # 2. Group permission
    groups: dict[str, Any] = perms.get("groups", {})
    for group_name, group_data in groups.items():
        if (group_name == "ALL" or sender in group_data.get("members", [])) and command in group_data.get("permissions", []):
            return True

    return False


def update_chat_history(msg: ChatMessage) -> None:
    chat_id: str = msg.chat_id
    if chat_id not in CHAT_HISTORY:
        CHAT_HISTORY[chat_id] = deque[ChatMessage](
            maxlen=settings.history_max_length)
    CHAT_HISTORY[chat_id].append(msg)
    # logger.debug(f"Chat history for {chat_id}: {CHAT_HISTORY[chat_id]}")
    # for line in CHAT_HISTORY[chat_id]:
    #    logger.debug(line)


def get_chat_id(data: dict[str, Any]) -> str | None:
    params = data.get("params", {})
    envelope = params.get("envelope", {})
    source = envelope.get("source")

    msg_payload = None
    if "dataMessage" in envelope:
        msg_payload = envelope.get("dataMessage")
    elif "syncMessage" in envelope:
        msg_payload = envelope.get("syncMessage", {}).get("sentMessage")

    group_id = None
    if msg_payload and "groupInfo" in msg_payload:
        group_id = msg_payload["groupInfo"].get("groupId")

    return group_id if group_id else source


def save_attachment(att: Attachment, dest_dir: str, filename: str | None = None) -> str | None:
    """
    Saves an attachment to the destination directory.
    """
    src: str = os.path.join(settings.signal_attachments_path, att.id)
    src = os.path.expanduser(src)

    if not os.path.exists(src):
        logger.warning(f"Attachment file not found: {src}")
        return None

    if filename:
        dest_name = filename
    else:
        dest_name = att.id
        if att.filename:
            safe_name: str = "".join(
                c if ('a' <= c <= 'z'
                      or 'A' <= c <= 'Z'
                      or '0' <= c <= '9'
                      or c in "._- "
                      )
                else "_" for c in att.filename
            )
            dest_name = safe_name

    dest: str = os.path.join(dest_dir, dest_name)
    try:
        shutil.copy2(src, dest)
        logger.info(f"Saved attachment {att.id} to {dest}")
        return dest
    except Exception as e:
        logger.error(f"Failed to copy attachment {src} to {dest}: {e}")
        return None
