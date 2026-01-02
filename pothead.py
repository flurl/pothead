from config import settings
import asyncio
from asyncio.subprocess import Process
from collections import deque
from dataclasses import dataclass
import json
import logging
import os
import sys
import time
import shutil
from typing import Any, Awaitable, Callable, cast, TypeAlias

from google import genai
from google.genai import types
from google.genai.pagers import Pager

Permissions: TypeAlias = dict[str, dict[str, list[str] | dict[str, list[str]]]]


@dataclass
class Attachment:
    content_type: str
    id: str
    size: int
    filename: str | None = None
    width: int | None = None
    height: int | None = None
    caption: str | None = None


@dataclass
class ChatMessage:
    sender: str
    text: str | None
    attachments: list[Attachment]

    def __str__(self) -> str:
        out: list[str] = []
        if self.text:
            out.append(self.text)
        if self.attachments:
            out.append(f"[Attachments: {len(self.attachments)}]")
            for att in self.attachments:
                name: str = att.filename if att.filename else att.id
                details: str = f"{name} ({att.content_type})"
                if att.caption:
                    details += f" Caption: {att.caption}"
                out.append(f"  - {details}")
        return "\n".join(out)


# --- CONFIGURATION ---
CHAT_HISTORY: dict[str, deque[ChatMessage]] = {}
CHAT_CONTEXT: dict[str, list[str]] = {}
CHAT_STORES: dict[str, types.FileSearchStore] = {}

# Configure logging
logging.basicConfig(
    level=settings.log_level.upper(),
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger: logging.Logger = logging.getLogger(__name__)

# Configure Gemini
client = genai.Client(api_key=settings.gemini_api_key)


@dataclass
class Command:
    name: str
    handler: Callable[[str, list[str], str | None],
                      Awaitable[tuple[str, list[str]]]]
    help_text: str


def get_local_files(chat_id: str) -> list[str]:
    chat_dir: str = os.path.join(settings.file_store_path, chat_id)
    if os.path.isdir(chat_dir):
        return sorted([f for f in os.listdir(chat_dir) if os.path.isfile(os.path.join(chat_dir, f))])
    return []


def get_permissions_file(chat_id: str) -> str:
    store_path: str = settings.permissions_store_path
    chat_dir: str = os.path.join(store_path, chat_id)
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


async def cmd_save(chat_id: str, params: list[str], prompt: str | None) -> tuple[str, list[str]]:
    """Saves prompt, history entries, and attachments to the store."""
    lines_to_save: list[str] = []
    attachments_to_save: list[Attachment] = []

    # Process parameters (history indices)
    if chat_id in CHAT_HISTORY:
        history: deque[ChatMessage] = CHAT_HISTORY[chat_id]

        # 1. Check current message (the command itself) for attachments
        if history:
            current_msg: ChatMessage = history[-1]
            if current_msg.attachments:
                attachments_to_save.extend(current_msg.attachments)

        # 2. Check requested history entries
        for p in params:
            try:
                idx = int(p)
                # 1-based index from end, skipping the command itself
                if 1 <= idx < len(history):
                    msg: ChatMessage = history[-idx-1]
                    if msg.text:
                        lines_to_save.append(msg.text)
                    if msg.attachments:
                        attachments_to_save.extend(msg.attachments)
            except ValueError:
                pass

    if prompt:
        lines_to_save.append(prompt)

    if not lines_to_save and not attachments_to_save:
        return "⚠️ Nothing to save.", []

    # File operations
    chat_dir: str = os.path.join(settings.file_store_path, chat_id)
    os.makedirs(chat_dir, exist_ok=True)

    # Save Text
    if lines_to_save:
        file_path: str = os.path.join(chat_dir, "saved_context.txt")
        try:
            with open(file_path, "a", encoding="utf-8") as f:
                for line in lines_to_save:
                    f.write(f"{line}\n")
        except Exception as e:
            return f"❌ Error writing file: {e}", []

    # Save Attachments
    saved_att_count = 0
    for att in attachments_to_save:
        src: str = os.path.join(settings.signal_attachments_path, att.id)
        if os.path.exists(src):
            # Determine destination filename
            dest_name: str = att.id
            if att.filename:
                safe_name: str = "".join(
                    c if ('a' <= c <= 'z'
                          or 'A' <= c <= 'Z'
                          or '0' <= c <= '9'
                          or c in "._-")
                    else "_" for c in att.filename
                )
                dest_name = f"{safe_name}"

            dest: str = os.path.join(chat_dir, dest_name)
            try:
                shutil.copy2(src, dest)
                saved_att_count += 1
                logger.info(f"Saved attachment {att.id} to {dest}")
            except Exception as e:
                logger.error(f"Failed to copy attachment {src} to {dest}: {e}")
        else:
            logger.warning(f"Attachment file not found: {src}")

    # Update Gemini Store
    # Invalidate cache and delete old store to force re-upload
    if chat_id in CHAT_STORES:
        store: types.FileSearchStore = CHAT_STORES[chat_id]
        if store.name is None:
            logger.error(f"Store name is None.")
            return f"❌ Store name is None.", []
        try:
            client.file_search_stores.delete(name=store.name)
        except Exception as e:
            logger.error(f"Failed to delete old store: {e}")
        del CHAT_STORES[chat_id]

    # Trigger recreation/upload
    get_chat_store(chat_id)

    return f"💾 Saved {len(lines_to_save)} text items and {saved_att_count} attachments to store.", []


async def cmd_ls_store(chat_id: str, params: list[str], prompt: str | None) -> tuple[str, list[str]]:
    """Lists files in local storage and remote Gemini store."""
    response_lines: list[str] = [f"📂 File Store for chat '{chat_id}':"]

    # 1. Local Files
    local_files = get_local_files(chat_id)

    response_lines.append(f"\n🏠 Local ({len(local_files)}):")
    if local_files:
        idx: int = 1
        for f in local_files:
            response_lines.append(f"  {idx:>3}: {f}")
            idx += 1
    else:
        response_lines.append("  (empty)")

    # 2. Remote Files
    response_lines.append("\n☁️ Remote (Gemini):")

    store: types.FileSearchStore | None = CHAT_STORES.get(chat_id)

    if not store:
        response_lines.append(
            "  (No active store in memory - send a message to initialize)")
    elif not store.name:
        response_lines.append("  (Store has no name)")
    else:
        try:
            remote_files: list[str] = []
            pager: Pager[types.Document] = client.file_search_stores.documents.list(
                parent=store.name)
            for f in pager:
                name: str | None = getattr(f, "display_name", None)
                if name is None:
                    name = getattr(f, "uri", getattr(f, "name", "Unknown"))
                name = cast(str, name)
                remote_files.append(name)

            remote_files.sort()

            response_lines.append(f"  (Store ID: {store.name.split('/')[-1]})")
            if remote_files:
                for f in remote_files:
                    response_lines.append(f"  - {f}")
            else:
                response_lines.append("  (empty)")

        except Exception as e:
            response_lines.append(f"  ❌ Error listing remote files: {e}")

    return "\n".join(response_lines), []


async def cmd_getfile(chat_id: str, params: list[str], prompt: str | None) -> tuple[str, list[str]]:
    if not params:
        return "⚠️ Usage: getfile,<fileindex:int>", []
    try:
        idx = int(params[0])
    except ValueError:
        return "⚠️ Usage: getfile,<fileindex:int>", []

    local_files: list[str] = get_local_files(chat_id)
    if 1 <= idx <= len(local_files):
        filename: str = local_files[idx-1]
        filepath: str = os.path.join(
            settings.file_store_path, chat_id, filename)
        return f"Here is {filename}", [filepath]

    return f"⚠️ File index {idx} not found.", []


async def cmd_add_ctx(chat_id: str, params: list[str], prompt: str | None = None) -> tuple[str, list[str]]:
    """Saves prompt and history entries as context for the next Gemini call."""
    if chat_id not in CHAT_CONTEXT:
        CHAT_CONTEXT[chat_id] = []

    saved_count = 0

    # Process parameters (history indices)
    if chat_id in CHAT_HISTORY:
        history: deque[ChatMessage] = CHAT_HISTORY[chat_id]
        for p in params:
            try:
                idx = int(p)
                if 1 <= idx <= 10 and idx <= len(history):
                    # 1-based index from end: 1 -> -1 (most recent)
                    # skip the last history entry which is the command itself
                    # therefore the -1
                    CHAT_CONTEXT[chat_id].append(str(history[-idx-1]))
                    saved_count += 1
            except ValueError:
                pass

    if prompt:
        CHAT_CONTEXT[chat_id].append(prompt)
        saved_count += 1

    return f"💾 Context saved ({saved_count} items). Will be used in next call.", []


async def cmd_ls_ctx(chat_id: str, params: list[str], prompt: str | None) -> tuple[str, list[str]]:
    print(CHAT_CONTEXT)
    """Lists the currently saved context for the chat."""
    if chat_id not in CHAT_CONTEXT or not CHAT_CONTEXT[chat_id]:
        return "ℹ️ No context is currently saved for this chat.", []

    context_items: list[str] = CHAT_CONTEXT[chat_id]
    response_lines: list[str] = ["📝 Current Context:"]
    for i, item in enumerate(context_items, 1):
        # Get first 5 words and add "..." if longer
        words: list[str] = item.split()
        snippet: str = " ".join(words[:5])
        if len(words) > 5:
            snippet += "..."
        response_lines.append(f"{i}. {snippet}")

    return "\n".join(response_lines), []


async def cmd_rm_ctx(chat_id: str, params: list[str], prompt: str | None) -> tuple[str, list[str]]:
    """Deletes all context for the current chat."""
    if chat_id in CHAT_CONTEXT:
        del CHAT_CONTEXT[chat_id]
        return "🗑️ Context cleared.", []
    return "ℹ️ No context to clear.", []


async def cmd_grant(chat_id: str, params: list[str], prompt: str | None) -> tuple[str, list[str]]:
    """Grants a command permission to a user."""
    if len(params) < 2:
        return "⚠️ Usage: grant,<command>,<user_id>", []

    cmd_name: str = params[0].lower()
    user_id: str = params[1]

    if not any(c.name == cmd_name for c in COMMANDS):
        return f"⚠️ Unknown command: {cmd_name}", []

    perms: Permissions = load_permissions(chat_id)
    if "users" not in perms:
        perms["users"] = {}
    if user_id not in perms["users"]:
        perms["users"][user_id] = []

    if cmd_name not in perms["users"][user_id]:
        cast(list[str], perms["users"][user_id]).append(cmd_name)
        save_permissions(chat_id, perms)
        return f"✅ Granted '{cmd_name}' to {user_id}.", []

    return f"ℹ️ {user_id} already has permission for '{cmd_name}'.", []


async def cmd_mkgroup(chat_id: str, params: list[str], prompt: str | None) -> tuple[str, list[str]]:
    """Creates a new user group."""
    if not params:
        return "⚠️ Usage: mkgroup,<group_name>", []

    group_name: str = params[0]
    perms: Permissions = load_permissions(chat_id)

    if "groups" not in perms:
        perms["groups"] = {}

    if group_name in perms["groups"]:
        return f"⚠️ Group '{group_name}' already exists.", []

    perms["groups"][group_name] = {"members": [], "permissions": []}
    save_permissions(chat_id, perms)
    return f"✅ Group '{group_name}' created.", []


async def cmd_addmember(chat_id: str, params: list[str], prompt: str | None) -> tuple[str, list[str]]:
    """Adds a user to a group."""
    if len(params) < 2:
        return "⚠️ Usage: addmember,<group_name>,<user_id>", []

    group_name: str = params[0]
    user_id: str = params[1]

    perms: Permissions = load_permissions(chat_id)
    if group_name not in perms.get("groups", {}):
        return f"⚠️ Group '{group_name}' not found.", []

    if user_id not in cast(dict[str, list[str]], perms["groups"][group_name])["members"]:
        cast(dict[str, list[str]], perms["groups"]
             [group_name])["members"].append(user_id)
        save_permissions(chat_id, perms)
        return f"✅ Added {user_id} to group '{group_name}'.", []

    return f"ℹ️ {user_id} is already in group '{group_name}'.", []


async def cmd_grantgroup(chat_id: str, params: list[str], prompt: str | None) -> tuple[str, list[str]]:
    """Grants a command permission to a group."""
    if len(params) < 2:
        return "⚠️ Usage: grantgroup,<command>,<group_name>", []

    cmd_name: str = params[0].lower()
    group_name: str = params[1]

    if not any(c.name == cmd_name for c in COMMANDS):
        return f"⚠️ Unknown command: {cmd_name}", []

    perms: Permissions = load_permissions(chat_id)
    if group_name not in perms.get("groups", {}):
        return f"⚠️ Group '{group_name}' not found.", []

    if cmd_name not in cast(dict[str, list[str]], perms["groups"][group_name])["permissions"]:
        cast(dict[str, list[str]], perms["groups"][group_name])[
            "permissions"].append(cmd_name)
        save_permissions(chat_id, perms)
        return f"✅ Granted '{cmd_name}' to group '{group_name}'.", []

    return f"ℹ️ Group '{group_name}' already has permission for '{cmd_name}'.", []


async def cmd_revoke(chat_id: str, params: list[str], prompt: str | None) -> tuple[str, list[str]]:
    """Revokes a command permission from a user."""
    if len(params) < 2:
        return "⚠️ Usage: revoke,<command>,<user_id>", []

    cmd_name: str = params[0].lower()
    user_id: str = params[1]

    perms: Permissions = load_permissions(chat_id)
    if "users" not in perms or user_id not in perms["users"]:
        return f"ℹ️ User {user_id} has no permissions to revoke.", []

    user_perms = cast(list[str], perms["users"][user_id])
    if cmd_name in user_perms:
        user_perms.remove(cmd_name)
        save_permissions(chat_id, perms)
        return f"✅ Revoked '{cmd_name}' from {user_id}.", []

    return f"ℹ️ {user_id} does not have permission for '{cmd_name}'.", []


async def cmd_rmmember(chat_id: str, params: list[str], prompt: str | None) -> tuple[str, list[str]]:
    """Removes a user from a group."""
    if len(params) < 2:
        return "⚠️ Usage: rmmember,<group_name>,<user_id>", []

    group_name: str = params[0]
    user_id: str = params[1]

    perms: Permissions = load_permissions(chat_id)
    if group_name not in perms.get("groups", {}):
        return f"⚠️ Group '{group_name}' not found.", []

    group_data = cast(dict[str, list[str]], perms["groups"][group_name])
    if user_id in group_data["members"]:
        group_data["members"].remove(user_id)
        save_permissions(chat_id, perms)
        return f"✅ Removed {user_id} from group '{group_name}'.", []

    return f"ℹ️ {user_id} is not in group '{group_name}'.", []


async def cmd_revokegroup(chat_id: str, params: list[str], prompt: str | None) -> tuple[str, list[str]]:
    """Revokes a command permission from a group."""
    if len(params) < 2:
        return "⚠️ Usage: revokegroup,<command>,<group_name>", []

    cmd_name: str = params[0].lower()
    group_name: str = params[1]

    perms: Permissions = load_permissions(chat_id)
    if group_name not in perms.get("groups", {}):
        return f"⚠️ Group '{group_name}' not found.", []

    group_data = cast(dict[str, list[str]], perms["groups"][group_name])
    if cmd_name in group_data["permissions"]:
        group_data["permissions"].remove(cmd_name)
        save_permissions(chat_id, perms)
        return f"✅ Revoked '{cmd_name}' from group '{group_name}'.", []

    return f"ℹ️ Group '{group_name}' does not have permission for '{cmd_name}'.", []


async def cmd_rmgroup(chat_id: str, params: list[str], prompt: str | None) -> tuple[str, list[str]]:
    """Deletes a user group."""
    if not params:
        return "⚠️ Usage: rmgroup,<group_name>", []

    group_name: str = params[0]
    perms: Permissions = load_permissions(chat_id)

    if group_name not in perms.get("groups", {}):
        return f"⚠️ Group '{group_name}' not found.", []

    del perms["groups"][group_name]
    save_permissions(chat_id, perms)
    return f"✅ Group '{group_name}' deleted.", []


async def cmd_lsperms(chat_id: str, params: list[str], prompt: str | None) -> tuple[str, list[str]]:
    """Lists all active permissions for the current chat."""
    perms: Permissions = load_permissions(chat_id)
    response_lines: list[str] = [f"🔐 Permissions for chat '{chat_id}':"]

    # Users
    users = perms.get("users", {})
    if users:
        response_lines.append("\n👤 User Permissions:")
        for user, cmds in cast(dict[str, list[str]], users).items():
            cmd_list = ", ".join(cmds) if cmds else "(none)"
            response_lines.append(f"  - {user}: {cmd_list}")
    else:
        response_lines.append("\n👤 User Permissions: (none)")

    # Groups
    groups = perms.get("groups", {})
    if groups:
        response_lines.append("\n👥 Group Permissions:")
        for group_name, data in cast(dict[str, dict[str, list[str]]], groups).items():
            members = ", ".join(data.get("members", []))
            cmds = ", ".join(data.get("permissions", []))
            response_lines.append(f"  - {group_name}:")
            response_lines.append(
                f"    Members: {members if members else '(none)'}")
            response_lines.append(
                f"    Commands: {cmds if cmds else '(none)'}")
    else:
        response_lines.append("\n👥 Group Permissions: (none)")

    return "\n".join(response_lines), []


async def cmd_help(chat_id: str, params: list[str], prompt: str | None) -> tuple[str, list[str]]:
    """Lists all available commands and their help text."""
    response_lines: list[str] = ["🛠️ Available Commands:"]
    for cmd in COMMANDS:
        response_lines.append(f"• {cmd.name}: {cmd.help_text}")
    return "\n".join(response_lines), []


COMMANDS: list[Command] = [
    Command("help", cmd_help, "Lists all available commands."),
    Command("addctx", cmd_add_ctx,
            "Adds the current prompt or history entries (by index) to the context for the next AI response."),
    Command("lsctx", cmd_ls_ctx, "Lists the currently active context items."),
    Command("rmctx", cmd_rm_ctx, "Clears the current context."),
    Command("save", cmd_save,
            "Saves the current prompt, history entries (by index), and attachments to the store."),
    Command("lsstore", cmd_ls_store,
            "Lists files in the local and remote file store."),
    Command("getfile", cmd_getfile,
            "Retrieves a file from the local store by its index."),
    Command("grant", cmd_grant, "Grants a command permission to a user."),
    Command("mkgroup", cmd_mkgroup, "Creates a new user group."),
    Command("addmember", cmd_addmember, "Adds a user to a group."),
    Command("grantgroup", cmd_grantgroup,
            "Grants a command permission to a group."),
    Command("revoke", cmd_revoke, "Revokes a command permission from a user."),
    Command("rmmember", cmd_rmmember, "Removes a user from a group."),
    Command("revokegroup", cmd_revokegroup,
            "Revokes a command permission from a group."),
    Command("rmgroup", cmd_rmgroup, "Deletes a user group."),
    Command("lsperms", cmd_lsperms,
            "Lists all active permissions for the current chat."),
]


async def execute_command(chat_id: str, sender: str, command: str, params: list[str], prompt: str | None = None) -> tuple[str, list[str]]:
    command = command.lower()
    """Executes the parsed command."""
    if not check_permission(chat_id, sender, command):
        return f"⛔ Permission denied for command: {command}", []

    for cmd in COMMANDS:
        if cmd.name == command:
            return await cmd.handler(chat_id, params, prompt)
    return f"❓ Unknown command: {command}", []


def update_chat_history(chat_id: str, sender: str, message: str | None, attachments: list[Attachment] | None = None) -> None:
    if attachments is None:
        attachments = []
    if chat_id not in CHAT_HISTORY:
        CHAT_HISTORY[chat_id] = deque[ChatMessage](
            maxlen=settings.history_max_length)
    CHAT_HISTORY[chat_id].append(ChatMessage(
        sender=sender, text=message, attachments=attachments))
    logger.debug(f"Chat history for {chat_id}: {CHAT_HISTORY[chat_id]}")
    for line in CHAT_HISTORY[chat_id]:
        logger.debug(line)


def get_chat_store(chat_id: str) -> types.FileSearchStore | None:
    if chat_id in CHAT_STORES:
        return CHAT_STORES[chat_id]

    chat_dir: str = os.path.join(settings.file_store_path, chat_id)
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

        CHAT_STORES[chat_id] = new_store
        return new_store
    except Exception as e:
        logger.error(f"Failed to create store for {chat_id}: {e}")
        return None


async def get_gemini_response(chat_id: str, prompt_text: str) -> str | None:
    """Sends text to Gemini and returns the response."""
    try:
        chat_store: types.FileSearchStore | None = get_chat_store(chat_id)

        parts: list[types.Part] = []
        # Add context if available and withdraw it
        if chat_id in CHAT_CONTEXT:
            for ctx in CHAT_CONTEXT[chat_id]:
                parts.append(types.Part(text=ctx))
            del CHAT_CONTEXT[chat_id]

        parts.append(types.Part(text=prompt_text))

        # Create a proper Content object for the prompt
        content = types.Content(parts=parts)

        tools: list[types.Tool] = []
        if chat_store and chat_store.name:
            tools.append(types.Tool(
                file_search=types.FileSearch(
                    file_search_store_names=[chat_store.name]
                )
            ))

        # Generate content
        response: types.GenerateContentResponse = await client.aio.models.generate_content(  # type: ignore
            model=settings.gemini_model_name,
            contents=content,
            config=types.GenerateContentConfig(
                system_instruction=settings.system_instruction,
                tools=tools if tools else None,
                safety_settings=[
                    types.SafetySetting(
                        category=types.HarmCategory.HARM_CATEGORY_HARASSMENT,
                        threshold=types.HarmBlockThreshold.BLOCK_NONE
                    ),
                    types.SafetySetting(
                        category=types.HarmCategory.HARM_CATEGORY_HATE_SPEECH,
                        threshold=types.HarmBlockThreshold.BLOCK_NONE
                    ),
                    types.SafetySetting(
                        category=types.HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT,
                        threshold=types.HarmBlockThreshold.BLOCK_NONE
                    ),
                    types.SafetySetting(
                        category=types.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT,
                        threshold=types.HarmBlockThreshold.BLOCK_NONE
                    ),
                ]
            ),
        )
        return response.text
    except Exception as e:
        return f"Error querying Gemini: {str(e)}"


async def send_signal_message(proc: Process, recipient: str, message: str, group_id: str | None = None, attachments: list[str] | None = None) -> None:
    """
    Sends a message back via signal-cli JSON-RPC.
    Supports direct messages (recipient) and group messages (group_id).
    """
    params: dict[str, Any] = {
        "account": settings.signal_account,
        "message": message
    }

    if group_id:
        params["groupId"] = group_id
    else:
        params["recipient"] = [recipient]

    if attachments:
        params["attachment"] = attachments

    rpc_request: dict[str, Any] = {
        "jsonrpc": "2.0",
        "method": "send",
        "params": params,
        "id": "reply-id"
    }

    # Write to signal-cli stdin
    try:
        assert proc.stdin is not None
        proc.stdin.write(json.dumps(rpc_request).encode('utf-8') + b"\n")
        await proc.stdin.drain()
    except Exception as e:
        logger.error(f"Failed to send message: {e}")


async def process_incoming_line(proc: Process, line: str) -> None:
    """Parses a line of JSON from signal-cli."""
    try:
        data: Any = json.loads(line)
    except json.JSONDecodeError:
        return

    # We only care about notifications (no 'id') with method 'receive'
    if data.get("method") == "receive":
        params = data.get("params", {})
        envelope = params.get("envelope", {})

        # 1. Filter by Sender immediately
        source: str = envelope.get("source")
        # if source != settings.target_sender:
        #    return

        # 2. Extract Message Body and Context (Group vs Direct)
        # We need to look in two places: dataMessage (incoming) and syncMessage (sent from other devices)
        message_body: str | None = None
        group_id: str | None = None
        quote: str | None = None
        attachments: list[Attachment] = []

        # Case A: Standard Incoming Message
        if "dataMessage" in envelope:
            dm = envelope["dataMessage"]
            if dm:
                message_body = dm.get("message")
                if "groupInfo" in dm:
                    group_id = dm["groupInfo"].get("groupId")
                if "quote" in dm:
                    quote = dm["quote"].get("text")
                if "attachments" in dm:
                    for att in dm["attachments"]:
                        attachments.append(Attachment(
                            content_type=att.get("contentType", "unknown"),
                            id=att.get("id", ""),
                            size=att.get("size", 0),
                            filename=att.get("filename"),
                            width=att.get("width"),
                            height=att.get("height"),
                            caption=att.get("caption")
                        ))

        # Case B: Sync Message (Sent from your other devices)
        elif "syncMessage" in envelope:
            sm = envelope["syncMessage"]
            if sm and "sentMessage" in sm:
                sent_msg = sm["sentMessage"]
                message_body = sent_msg.get("message")
                # Check if it was sent to a group
                if "groupInfo" in sent_msg:
                    group_id = sent_msg["groupInfo"].get("groupId")
                if "quote" in sm:
                    quote = sm["quote"].get("text")
                if "attachments" in sent_msg:
                    for att in sent_msg["attachments"]:
                        attachments.append(Attachment(
                            content_type=att.get("contentType", "unknown"),
                            id=att.get("id", ""),
                            size=att.get("size", 0),
                            filename=att.get("filename"),
                            width=att.get("width"),
                            height=att.get("height"),
                            caption=att.get("caption")
                        ))

        # If no text found, ignore (e.g., receipts, typing indicators)
        if not message_body and not attachments:
            return

        chat_id: str = group_id if group_id else source
        update_chat_history(chat_id, source, message_body, attachments)

        # 3. Check Prefixes (!pothead or !pot or !ph)
        clean_msg: str = message_body.strip() if message_body else ""
        prompt: str | None = None
        command: str | None = None
        command_params: list[str] = []

        if quote is not None:
            prompt = f"{prompt}\n\n{quote}"

        settings.trigger_words.sort(key=len, reverse=True)
        for tw in settings.trigger_words:
            if clean_msg.startswith(tw):
                content: str = clean_msg[len(tw):].strip()
                if content.startswith("#"):
                    # Parse command
                    # Syntax: !TRIGGERWORD#COMMAND,PARAM1,PARAM2,... PROMPT
                    cmd_content: str = content[1:]
                    cmd_part: str
                    prompt_part: str
                    if " " in cmd_content:
                        cmd_part, prompt_part = cmd_content.split(" ", 1)
                        prompt = prompt_part.strip()
                    else:
                        cmd_part: str = cmd_content
                        prompt = None

                    parts: list[str] = cmd_part.split(',')
                    command = parts[0].strip()
                    if len(parts) > 1:
                        command_params = [p.strip() for p in parts[1:]]
                else:
                    prompt = content
                break

        # 4. Process
        if command is not None:
            logger.info(
                f"Processing command from {source} (Group: {group_id}): {command} {command_params}")
            response_text: str | None = None
            response_attachments: list[str] = []
            response_text, response_attachments = await execute_command(chat_id, source, command, command_params, prompt)
            await send_signal_message(proc, source, response_text, group_id, response_attachments)
            logger.info(f"Sent response to {source}")

        elif prompt is not None:
            logger.info(
                f"Processing request from {source} (Group: {group_id}): {prompt}")

            if not prompt:
                response_text = "🤖 Beep Boop. Please provide a prompt."
            else:
                response_text: str | None = await get_gemini_response(chat_id, prompt)

            # 5. Send Response
            # If group_id exists, we reply to the group. If not, we reply to the source.
            if response_text is None:
                response_text = "🤖 Beep Boop. Something went wrong."

            update_chat_history(chat_id, "Assistant", response_text)

            await send_signal_message(proc, source, response_text, group_id)
            logger.info(f"Sent response to {source}")


async def main() -> None:
    # Start signal-cli in jsonRpc mode
    # -a specifies the account sending/receiving
    cmd: list[str] = [settings.signal_cli_path, "-a",
                      settings.signal_account, "jsonRpc"]  # type: ignore

    logger.info(f"Starting signal-cli: {' '.join(cmd)}")

    proc: Process = await asyncio.create_subprocess_exec(
        *cmd,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=sys.stderr  # Print errors to console directly
    )

    logger.info("Listening for messages...")

    try:
        while True:
            assert proc.stdout is not None
            # Read line by line from signal-cli stdout
            line: bytes = await proc.stdout.readline()
            # logger.debug(f"received: {line}")
            if not line:
                break

            decoded_line: str = line.decode('utf-8').strip()
            if decoded_line:
                # Process each line asynchronously so we don't block reading
                asyncio.create_task(process_incoming_line(proc, decoded_line))

    except asyncio.CancelledError:
        pass
    finally:
        if proc.returncode is None:
            proc.terminate()
            await proc.wait()

if __name__ == "__main__":
    asyncio.run(main())
