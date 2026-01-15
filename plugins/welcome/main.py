"""
This plugin provides a welcome message functionality for Signal groups.
It monitors group updates, identifies new members, and sends a predefined
welcome message to the group when new members join.

Features:
- **Group Member Tracking:** Keeps a record of group members to detect new additions.
- **Automatic Welcome Message:** Sends a customizable welcome message to the group
  when new members are detected.
- **Welcome Message Customization:** Allows saving a text file as the welcome message
  using a command.
- **Initialization Command:** Provides a command to initialize the plugin for a group,
  saving current members and optionally setting a welcome message.
"""

import asyncio
from collections import deque
from dataclasses import dataclass
import logging
import os
from typing import Any

from datatypes import Attachment, ChatMessage
from messaging import send_signal_group_message, get_group_info
from plugin_manager import register_action, register_command
from state import CHAT_HISTORY
from utils import get_safe_chat_dir, save_attachment


logger: logging.Logger = logging.getLogger(__name__)


@dataclass
class Member:
    number: str | None
    uuid: str
    username: str | None = None


def extract_members(data: dict[str, Any]) -> list[Member]:
    result: list[dict[str, Any]] = data.get("result", [])
    members: list[Member] = []
    for group in result:
        members = [Member(
            number=m.get("number"),
            uuid=m.get("uuid"),
            username=m.get("username", None)
        ) for m in group.get("members", [])]
        logger.info(f"Extracted members: {members}")
    return members


def get_group_dir(chat_id: str) -> str:
    plugin_dir: str = os.path.dirname(__file__)
    chat_dir: str = get_safe_chat_dir(plugin_dir, chat_id)
    os.makedirs(chat_dir, exist_ok=True)
    return chat_dir


def find_new_members(chat_id: str, members: list[Member]) -> list[Member]:
    file_path: str = os.path.join(get_group_dir(chat_id), "members.csv")
    existing_members_numbers: set[str] = set()
    if os.path.exists(file_path):
        with open(file_path, "r") as f:
            for line in f:
                line = line.strip()
                if line:
                    parts: list[str] = line.split(',')
                    if parts:
                        existing_members_numbers.add(parts[0])

    new_members: list[Member] = []
    for member in members:
        if member.number and member.number not in existing_members_numbers:
            new_members.append(member)

    return new_members


def save_members(chat_id: str, members: list[Member]) -> None:
    # save the list of members as csv in the plugins directory in the file members.csv
    file_path: str = os.path.join(get_group_dir(chat_id), "members.csv")
    with open(file_path, "w") as f:
        for m in members:
            f.write(f"{m.number},{m.uuid},{m.username}\n")
    logger.info(f"Saved members for chat {chat_id} to {file_path}")


async def group_info_handler(data: dict[str, Any]) -> None:
    logger.debug(f"Received group info: {data}")
    chat_id: str | None = data.get("result", [])[0].get("id")
    if not chat_id:
        logger.error("No chat_id found in data.")
        return

    members: list[Member] = extract_members(data)
    new_members: list[Member] = find_new_members(chat_id, members)
    if new_members:
        logger.info(f"New members found: {new_members}")
        await send_welcome_message(chat_id)

    save_members(chat_id, members)


async def send_welcome_message(chat_id: str) -> None:
    group_dir: str = get_group_dir(chat_id)
    file_path: str = os.path.join(group_dir, "welcome_message.txt")
    if os.path.exists(file_path):
        with open(file_path, "r") as f:
            welcome_message: str = f.read()
            await send_signal_group_message(welcome_message, chat_id)


@register_action(
    "welcome",
    name="Check for group updates",
    jsonpath='$.params.envelope.syncMessage.sentMessage.groupInfo.type',
    filter=lambda match: match.value and match.value == "UPDATE",
)
async def action_group_update(data: dict[str, Any]) -> bool:
    """
    This is called when a group update is received.
    in that case a group info is requested to get the list of members.
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
    print(f"{message_body=}, {group_id=}")

    # Avoid echoing commands or empty messages
    if source and group_id:
        logger.info(f"Got group update for group {group_id}")
        await get_group_info(group_id, group_info_handler)
    return True


@register_command("welcome", "initgroup",
                  "Stores the current list of group members and optionally saves an attachment as welcome message.")
async def cmd_initgroup(chat_id: str, params: list[str], prompt: str | None) -> tuple[str, list[str]]:
    loop: asyncio.AbstractEventLoop = asyncio.get_running_loop()
    future: asyncio.Future[Any] = loop.create_future()

    async def callback(data: dict[str, Any]) -> None:
        future.set_result(data)

    await get_group_info(chat_id, callback)

    data: dict[str, Any] = await future
    members: list[Member] = extract_members(data)

    save_members(chat_id, members)

    attachments_to_save: list[Attachment] = []

    # Process parameters (history indices)
    if chat_id in CHAT_HISTORY:
        history: deque[ChatMessage] = CHAT_HISTORY[chat_id]
        # 1. Check current message (the command itself) for attachments
        if history:
            current_msg: ChatMessage = history[-1]
            if current_msg.attachments:
                attachments_to_save.extend(current_msg.attachments)

    if attachments_to_save:
        for att in attachments_to_save:
            is_text: bool = att.content_type.startswith("text/")
            if not is_text and att.filename:
                _: str
                ext: str
                _, ext = os.path.splitext(att.filename)
                if ext.lower() in [".txt", ".md", ".markdown"]:
                    is_text = True

            if not is_text:
                return "Only text files (txt, md) are valid.", []
            dest_name: str = f"welcome_message{os.path.splitext(att.id)[1]}"
            save_attachment(att, get_group_dir(chat_id), dest_name)

    return f"initialized group {chat_id}", []
