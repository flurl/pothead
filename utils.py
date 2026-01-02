
import hashlib
import json
import logging
import os
import time
from typing import Any

from config import settings
from google.genai import types
from google.genai.client import Client

from datatypes import Permissions

logger: logging.Logger = logging.getLogger(__name__)


def get_safe_chat_dir(base_path: str, chat_id: str) -> str:
    hashed_id = hashlib.sha256(chat_id.encode("utf-8")).hexdigest()
    return os.path.join(base_path, hashed_id)


def get_local_files(chat_id: str) -> list[str]:
    chat_dir: str = get_safe_chat_dir(settings.file_store_path, chat_id)
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


def get_chat_store(chat_id: str, chat_stores: dict[str, types.FileSearchStore], client: Client) -> types.FileSearchStore | None:
    if chat_id in chat_stores:
        return chat_stores[chat_id]

    chat_dir: str = get_safe_chat_dir(settings.file_store_path, chat_id)
    if not os.path.isdir(chat_dir):
        logger.info(f"No file store found for chat {chat_id}.")
        return None

    files: list[str] = [f for f in os.listdir(
        chat_dir) if os.path.isfile(os.path.join(chat_dir, f))]
    if not files:
        return None

    logger.info(f"Creating file store for chat {chat_id}...")
    try:
        new_store: types.FileSearchStore = client.file_search_stores.create(
            config={"display_name": chat_id})

        if not new_store or not new_store.name:
            return None

        for filename in files:
            full_path: str = os.path.join(chat_dir, filename)
            logger.info(f"Uploading {full_path}...")
            upload_op = client.file_search_stores.upload_to_file_search_store(
                file_search_store_name=new_store.name,
                file=full_path
            )
            while not upload_op.done:
                logger.info(f"Waiting for {filename}...")
                time.sleep(2)
                upload_op: types.UploadToFileSearchStoreOperation = client.operations.get(
                    upload_op)

        chat_stores[chat_id] = new_store
        return new_store
    except Exception as e:
        logger.error(f"Failed to create store for {chat_id}: {e}")
        return None
