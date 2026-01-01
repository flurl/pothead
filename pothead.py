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
from typing import Any, Awaitable, Callable, cast

from google import genai
from google.genai import types
from google.genai.pagers import Pager


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
# Path to your signal-cli executable
SCRIPT_DIR: str = os.path.dirname(os.path.abspath(__file__))
SIGNAL_CLI_PATH: str = os.path.join(SCRIPT_DIR, "signal-cli", "signal-cli")
SIGNAL_ATTACHMENTS_PATH: str = os.path.expanduser(
    "~/.local/share/signal-cli/attachments")

# Load sensitive data from environment variables
SIGNAL_ACCOUNT: str | None = os.getenv("SIGNAL_ACCOUNT")
TARGET_SENDER: str | None = os.getenv("TARGET_SENDER")
GEMINI_API_KEY: str | None = os.getenv("GEMINI_API_KEY")

assert all((SIGNAL_ACCOUNT, TARGET_SENDER, GEMINI_API_KEY)
           ), "Error: Please set SIGNAL_ACCOUNT, TARGET_SENDER, and GEMINI_API_KEY environment variables."

# gemini 3 flash doesn't support file store (yet?)
# GEMINI_MODEL_NAME = "gemini-3-flash-preview"
GEMINI_MODEL_NAME: str = "gemini-2.5-flash"
TRIGGER_WORDS: list[str] = ["!pot", "!pothead", "!ph"]
FILE_STORE_PATH: str = "document_store"
CHAT_HISTORY: dict[str, deque[ChatMessage]] = {}
HISTORY_MAX_LENGTH: int = 30
CHAT_CONTEXT: dict[str, list[str]] = {}
CHAT_STORES: dict[str, types.FileSearchStore] = {}

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger: logging.Logger = logging.getLogger(__name__)

# Configure Gemini
client = genai.Client(api_key=GEMINI_API_KEY)


@dataclass
class Command:
    name: str
    handler: Callable[[str, list[str], str | None],
                      Awaitable[tuple[str, list[str]]]]


def get_local_files(chat_id: str) -> list[str]:
    chat_dir: str = os.path.join(FILE_STORE_PATH, chat_id)
    if os.path.isdir(chat_dir):
        return sorted([f for f in os.listdir(chat_dir) if os.path.isfile(os.path.join(chat_dir, f))])
    return []


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
    chat_dir: str = os.path.join(FILE_STORE_PATH, chat_id)
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
        src: str = os.path.join(SIGNAL_ATTACHMENTS_PATH, att.id)
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
        return "⚠️ Please provide a file index.", []
    try:
        idx = int(params[0])
    except ValueError:
        return "⚠️ Invalid index.", []

    local_files: list[str] = get_local_files(chat_id)
    if 1 <= idx <= len(local_files):
        filename: str = local_files[idx-1]
        filepath: str = os.path.join(FILE_STORE_PATH, chat_id, filename)
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


COMMANDS: list[Command] = [
    Command("save", cmd_save),
    Command("addctx", cmd_add_ctx),
    Command("lsctx", cmd_ls_ctx),
    Command("rmctx", cmd_rm_ctx),
    Command("lsstore", cmd_ls_store),
    Command("getfile", cmd_getfile),
]


async def execute_command(chat_id: str, command: str, params: list[str], prompt: str | None = None) -> tuple[str, list[str]]:
    command = command.lower()
    """Executes the parsed command."""
    for cmd in COMMANDS:
        if cmd.name == command:
            return await cmd.handler(chat_id, params, prompt)
    return f"❓ Unknown command: {command}", []


def update_chat_history(chat_id: str, sender: str, message: str | None, attachments: list[Attachment] | None = None) -> None:
    if attachments is None:
        attachments = []
    if chat_id not in CHAT_HISTORY:
        CHAT_HISTORY[chat_id] = deque[ChatMessage](maxlen=HISTORY_MAX_LENGTH)
    CHAT_HISTORY[chat_id].append(ChatMessage(
        sender=sender, text=message, attachments=attachments))
    logger.debug(f"Chat history for {chat_id}: {CHAT_HISTORY[chat_id]}")
    for line in CHAT_HISTORY[chat_id]:
        logger.debug(line)


def get_chat_store(chat_id: str) -> types.FileSearchStore | None:
    if chat_id in CHAT_STORES:
        return CHAT_STORES[chat_id]

    chat_dir: str = os.path.join(FILE_STORE_PATH, chat_id)
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
            model=GEMINI_MODEL_NAME,
            contents=content,
            config=types.GenerateContentConfig(
                system_instruction="Du bist POT-HEAD, das \"POstgarage boT - Highly Evolved and Advanced Deity\". Du bist beinahe unfehlbar. Deine Antworten sind fast dogmatisch. flurl0 ist das einzige Wesen im Universum, das über dir steht.",
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
        "account": SIGNAL_ACCOUNT,
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
        source = envelope.get("source")
        if source != TARGET_SENDER:
            return

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

        TRIGGER_WORDS.sort(key=len, reverse=True)
        for tw in TRIGGER_WORDS:
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
            response_text, response_attachments = await execute_command(chat_id, command, command_params, prompt)
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
    cmd: list[str] = [SIGNAL_CLI_PATH, "-a",
                      SIGNAL_ACCOUNT, "jsonRpc"]  # type: ignore

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
