import logging
import os
import shutil
from collections import deque
from typing import cast

# from google.genai import types


from config import settings
from datatypes import Attachment, ChatMessage, Permissions, Command
from state import CHAT_HISTORY
from utils import get_local_files, get_safe_chat_dir, load_permissions, save_permissions


logger: logging.Logger = logging.getLogger(__name__)


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
    chat_dir: str = get_safe_chat_dir(settings.file_store_path, chat_id)
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
        src = os.path.expanduser(src)
        if os.path.exists(src):
            # Determine destination filename
            dest_name: str = att.id
            if att.filename:
                safe_name: str = "".join(
                    c if ('a' <= c <= 'z'
                          or 'A' <= c <= 'Z'
                          or '0' <= c <= '9'
                          or c in "._- "
                          )
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

    return f"💾 Saved {len(lines_to_save)} text items and {saved_att_count} attachments to store.", []


async def cmd_ls_store(chat_id: str, params: list[str], prompt: str | None) -> tuple[str, list[str]]:
    """Lists files in local storage and remote Gemini store."""
    response_lines: list[str] = [f"📂 File Store for chat '{chat_id}':"]
    local_files: list[str] = get_local_files(chat_id)

    response_lines.append(f"\n🏠 Local ({len(local_files)}):")
    if local_files:
        idx: int = 1
        for f in local_files:
            response_lines.append(f"  {idx:>3}: {f}")
            idx += 1
    else:
        response_lines.append("  (empty)")

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
        chat_dir: str = get_safe_chat_dir(settings.file_store_path, chat_id)
        filepath: str = os.path.join(chat_dir, filename)
        return f"Here is {filename}", [filepath]

    return f"⚠️ File index {idx} not found.", []


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

    if user_id not in cast(dict[str, list[str]], perms["groups"][
            group_name])["members"]:
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

    if cmd_name not in cast(dict[str, list[str]], perms["groups"][
            group_name])["permissions"]:
        cast(dict[str, list[str]], perms["groups"][
            group_name])["permissions"].append(cmd_name)
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

    group_data = cast(dict[str, list[str]], perms["groups"][
        group_name])
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

    group_data = cast(dict[str, list[str]], perms["groups"][
        group_name])
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


async def cmd_lsdirs(chat_id: str, params: list[str], prompt: str | None) -> tuple[str, list[str]]:
    """Lists the safe filesystem paths for the current chat."""
    file_store_path: str = get_safe_chat_dir(settings.file_store_path, chat_id)
    permissions_path: str = get_safe_chat_dir(
        settings.permissions_store_path, chat_id)

    response_lines: list[str] = [f"📂 Safe Paths for chat '{chat_id}':"]
    response_lines.append(f"  - File Store: {file_store_path}")
    response_lines.append(f"  - Permissions: {permissions_path}")

    return "\n".join(response_lines), []


async def cmd_help(chat_id: str, params: list[str], prompt: str | None) -> tuple[str, list[str]]:
    """Lists all available commands and their help text."""
    response_lines: list[str] = ["🛠️ Available Commands:"]
    by_origin: dict[str, list[Command]] = {}
    for cmd in COMMANDS:
        if cmd.origin not in by_origin:
            by_origin[cmd.origin] = []
        by_origin[cmd.origin].append(cmd)

    for origin, cmds in sorted(by_origin.items()):
        response_lines.append(f"\n{origin.upper()}:")
        for cmd in cmds:
            response_lines.append(f"  • {cmd.name}: {cmd.help_text}")
    return "\n".join(response_lines), []


COMMANDS: list[Command] = [
    Command("help", cmd_help, "Lists all available commands.", "sys"),
    Command("save", cmd_save,
            "Saves the current prompt, history entries (by index), and attachments to the store.\n    Params: [<index1>,<index2>,...]", "sys"),
    Command("lsstore", cmd_ls_store,
            "Lists files in the local and remote file store.", "sys"),
    Command("getfile", cmd_getfile,
            "Retrieves a file from the local store by its index.\n    Params: <file_index>", "sys"),
    Command("grant", cmd_grant,
            "Grants a command permission to a user.\n    Params: <command>,<user_id>", "sys"),
    Command("mkgroup", cmd_mkgroup,
            "Creates a new user group.\n    Params: <group_name>", "sys"),
    Command("addmember", cmd_addmember,
            "Adds a user to a group.\n    Params: <group_name>,<user_id>", "sys"),
    Command("grantgroup", cmd_grantgroup,
            "Grants a command permission to a group.\n    Params: <command>,<group_name>", "sys"),
    Command("revoke", cmd_revoke,
            "Revokes a command permission from a user.\n    Params: <command>,<user_id>", "sys"),
    Command("rmmember", cmd_rmmember,
            "Removes a user from a group.\n    Params: <group_name>,<user_id>", "sys"),
    Command("revokegroup", cmd_revokegroup,
            "Revokes a command permission from a group.\n    Params: <command>,<group_name>", "sys"),
    Command("rmgroup", cmd_rmgroup,
            "Deletes a user group.\n    Params: <group_name>", "sys"),
    Command("lsperms", cmd_lsperms,
            "Lists all active permissions for the current chat.", "sys"),
    Command("lsdirs", cmd_lsdirs,
            "Lists the safe filesystem paths for the current chat.", "sys"),
]
