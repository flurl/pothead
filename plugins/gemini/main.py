"""
This plugin integrates with the Google Gemini API to provide AI capabilities.
It allows users to interact with the Gemini model, manage conversation context,
and synchronize local files with Gemini's File Search Store for Retrieval Augmented Generation (RAG).

Features:
- **AI Chat:** Send messages to Gemini and receive responses.
- **Context Management:** Add previous messages or prompts to a temporary context
  for multi-turn conversations.
- **File Search Store (RAG):** Synchronize local files (from the bot's file store)
  with Gemini's File Search Store to enable the AI to retrieve information from
  these documents.

Configuration:
- `gemini_api_key`: Your Google Gemini API key.
- `gemini_model_name`: The name of the Gemini model to use (e.g., "gemini-pro").
- `system_instruction`: A system-level instruction for the Gemini model.
- `trigger_words`: Words that trigger the AI to process a message.
"""

import asyncio
import json
import io
import logging
import os
from collections import deque
from typing import cast

from google.genai.client import Client
from google.genai import types
from google.genai.pagers import Pager
from PIL import Image

from config import settings
from datatypes import ChatMessage, Event, MessageType
from messaging import send_signal_direct_message, send_signal_group_message
from plugin_manager import get_plugin_settings, register_command, register_event_handler, register_service
from state import CHAT_HISTORY
from utils import get_local_files, get_safe_chat_dir, update_chat_history

logger: logging.Logger = logging.getLogger(__name__)

plugin_id: str = "gemini"

from plugins.gemini.config import PluginSettings  # nopep8
plugin_settings: PluginSettings = cast(
    PluginSettings, get_plugin_settings(plugin_id))


SYS_INSTRUCTIONS_FILE: str = os.path.join(
    os.path.dirname(__file__), "sys_instructions.txt")
custom_sys_instructions: dict[str, str] = {}


def load_sys_instructions() -> None:
    global custom_sys_instructions
    if os.path.exists(SYS_INSTRUCTIONS_FILE):
        try:
            with open(SYS_INSTRUCTIONS_FILE, "r", encoding="utf-8") as f:
                custom_sys_instructions = json.load(f)
        except Exception as e:
            logger.error(f"Failed to load sys instructions: {e}")


def save_sys_instructions() -> None:
    try:
        with open(SYS_INSTRUCTIONS_FILE, "w", encoding="utf-8") as f:
            json.dump(custom_sys_instructions, f, indent=2)
    except Exception as e:
        logger.error(f"Failed to save sys instructions: {e}")


def image_to_part(path: str) -> types.Part | None:
    try:
        pil_image: Image.Image = Image.open(path)

        # Convert to RGB to ensure JPEG compatibility
        if pil_image.mode in ("RGBA", "P"):
            pil_image = pil_image.convert("RGB")

        image_buffer = io.BytesIO()
        pil_image.save(image_buffer, format="JPEG")
        image_bytes: bytes = image_buffer.getvalue()

        return types.Part(inline_data=types.Blob(mime_type="image/jpeg", data=image_bytes))
    except Exception as e:
        logger.error(f"Failed to process image {path}: {e}")
        return None


class GeminiProvider:
    def __init__(self, api_key: str) -> None:
        self._client = Client(api_key=api_key)
        self._chat_stores: dict[str, types.FileSearchStore] = {}
        self._chat_contexts: dict[str, list[str]] = {}

        # Pre-define safety settings to avoid recreation on every call
        self._safety_settings: list[types.SafetySetting] = [
            types.SafetySetting(
                category=cat,
                threshold=types.HarmBlockThreshold.BLOCK_NONE
            ) for cat in [
                types.HarmCategory.HARM_CATEGORY_HARASSMENT,
                types.HarmCategory.HARM_CATEGORY_HATE_SPEECH,
                types.HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT,
                types.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT,
            ]
        ]

    @property
    def client(self) -> Client:
        return self._client

    def get_chat_context(self, chat_id: str) -> list[str]:
        return self._chat_contexts.setdefault(chat_id, [])

    def get_chat_store(self, chat_id: str) -> types.FileSearchStore | None:
        if chat_id in self._chat_stores:
            return self._chat_stores[chat_id]

        logger.info(f"Creating file store reference for chat {chat_id}...")
        try:
            # Note: This creates a remote store. You might want to check if one exists
            # via API listing if your bot restarts, otherwise you create duplicates.
            new_store: types.FileSearchStore = self._client.file_search_stores.create(
                config={"display_name": chat_id}
            )
            if new_store and new_store.name:
                self._chat_stores[chat_id] = new_store
                return new_store
        except Exception as e:
            logger.error(
                f"Failed to create store for {chat_id}: {e}", exc_info=True)
        return None

    async def get_response(self, chat_id: str, parts: list[types.Part]) -> str:
        """Sends text to Gemini and returns the response."""
        try:
            # Inject and consume context
            context_list: list[str] = self.get_chat_context(chat_id)
            if context_list:
                parts.extend([types.Part(text=ctx) for ctx in context_list])
                context_list.clear()  # Clear after usage as per original logic

            # Configure Tools (RAG)
            tools: list[types.Tool] | None = None
            chat_store: types.FileSearchStore | None = self.get_chat_store(
                chat_id)
            if chat_store and chat_store.name:
                tools = [types.Tool(
                    file_search=types.FileSearch(
                        file_search_store_names=[chat_store.name]
                    )
                )]

            sys_instr: str = custom_sys_instructions.get(
                chat_id, plugin_settings.system_instruction)

            # Async Generation
            response: types.GenerateContentResponse = await self.client.aio.models.generate_content(  # type: ignore
                model=plugin_settings.gemini_model_name,
                contents=types.Content(parts=parts),
                config=types.GenerateContentConfig(
                    system_instruction=sys_instr,
                    tools=tools,
                    safety_settings=self._safety_settings,
                ),
            )
            return response.text if response.text else "🤖 (No text returned)"

        except Exception as e:
            logger.error(f"Gemini API Error: {e}", exc_info=True)
            return f"⚠️ Error querying Gemini: {str(e)}"


gemini = GeminiProvider(api_key=plugin_settings.gemini_api_key)


async def process_gemini_message(msg: ChatMessage, prompt: str | None = None) -> None:
    """
    Processes a message with Gemini, sends the response, and updates history.

    :param msg: The incoming chat message.
    :param prompt: The specific prompt text to send. If None, uses msg.text.
                   If msg.quote exists, it is appended.
    """
    # Determine the base prompt text
    text_to_process: str = prompt if prompt is not None else (msg.text or "")

    # Append quote to prompt if it exists
    full_prompt: str = text_to_process
    if msg.quote and msg.quote.text:
        full_prompt = f"{full_prompt}\n\n>> {msg.quote.text}"

    logger.info(
        f"Processing Gemini request from {msg.source} in {msg.chat_id}")

    parts: list[types.Part] = []
    if full_prompt:
        parts.append(types.Part(text=full_prompt))

    if msg.attachments:
        for att in msg.attachments:
            if att.content_type.startswith("image/"):
                path: str = os.path.join(
                    settings.signal_attachments_path, att.id)
                path: str = os.path.expanduser(path)
                if os.path.exists(path):
                    part: types.Part | None = image_to_part(path)
                    if part:
                        parts.append(part)

    if not parts:
        response_text = "🤖 Beep Boop. Please provide a prompt or image."
    else:
        response_text: str = await gemini.get_response(msg.chat_id, parts)

    # TODO: is this the correct place for updating the history?
    # Shouldn't that better be handeled by the send_* functions
    update_chat_history(ChatMessage(source="Assistant", source_name="Assistant",
                        destination=msg.chat_id, text=response_text, type=MessageType.CHAT))
    if msg.group_id:
        await send_signal_group_message(response_text, msg.group_id)
    elif msg.source == settings.signal_account:
        await send_signal_direct_message(response_text, msg.chat_id)
    else:
        # For direct messages, the recipient of the reply is the original source
        await send_signal_direct_message(response_text, msg.source)


async def chat_with_gemini(chat_id: str) -> None:
    if chat_id not in CHAT_HISTORY:
        return

    history: deque[ChatMessage] = CHAT_HISTORY[chat_id]
    if not history:
        return

    # Check if the last message in a chat is older than settings.context_expiry_threshold
    # We look for the last gap in conversation
    threshold_ms: int = plugin_settings.context_expiry_threshold * 1000
    start_index: int = 0

    for i in range(len(history) - 1, 0, -1):
        if (history[i].timestamp - history[i - 1].timestamp) > threshold_ms:
            start_index = i
            break

    parts: list[types.Part] = []
    for msg in list(history)[start_index:]:
        role: str = "Model" if msg.source == "Assistant" else f"User ({msg.source})"
        text: str = f"{role}: {msg.text or ''}"
        if msg.quote and msg.quote.text:
            text += f"\nQuote: {msg.quote.text}"
        # logger.debug(
        #    f"Adding to context: {text}")
        parts.append(types.Part(text=text))

        if msg.attachments:
            for att in msg.attachments:
                if att.content_type.startswith("image/"):
                    path: str = os.path.join(
                        settings.signal_attachments_path, att.id)
                    path = os.path.expanduser(path)
                    if os.path.exists(path):
                        part: types.Part | None = image_to_part(path)
                        if part:
                            parts.append(part)

    if not parts:
        return

    response_text: str = await gemini.get_response(chat_id, parts)

    last_msg: ChatMessage = history[-1]
    # TODO: is this the correct place for updating the history?
    # Shouldn't that better be handeled by the send_* functions
    update_chat_history(ChatMessage(source="Assistant", source_name="Assistant",
                        destination=chat_id, text=response_text, type=MessageType.CHAT))

    if last_msg.group_id:
        await send_signal_group_message(response_text, last_msg.group_id)
    elif last_msg.source == settings.signal_account:
        await send_signal_direct_message(response_text, last_msg.chat_id)
    else:
        await send_signal_direct_message(response_text, last_msg.source)


@register_service("send_to_ai")
async def send_to_ai(msg: ChatMessage) -> bool:
    await process_gemini_message(msg)
    return True


@register_service("chat_with_ai")
async def chat_with_ai(msg: ChatMessage) -> bool:
    await chat_with_gemini(msg.chat_id)
    return True


def _extract_gemini_prompt(msg: ChatMessage) -> tuple[str | None, bool]:
    """
    Checks whether the message should be processed by Gemini and returns the prompt.

    In dedicated_account mode: process if the bot is the direct recipient or is @mentioned.
    Otherwise: process if the message starts with a trigger word.

    Returns (prompt, should_process).
    """
    if settings.dedicated_account:
        is_recipient: bool = msg.destination == settings.signal_account
        is_mentioned: bool = msg.mentions is not None and any(
            m.number == settings.signal_account for m in msg.mentions
        )
        if not (is_recipient or is_mentioned):
            return None, False
        clean_msg: str = msg.text and msg.text.strip() or ""
        if clean_msg.startswith("#"):
            return None, False
        return clean_msg or None, bool(clean_msg or msg.attachments)

    clean_msg = msg.text and msg.text.strip() or ""
    for tw in sorted(settings.trigger_words, key=len, reverse=True):
        if clean_msg.upper().startswith(tw.upper()):
            content: str = clean_msg[len(tw):].strip()
            if content.startswith("#"):
                return None, False
            return content, True
    if not clean_msg and msg.attachments:
        return None, True
    return None, False


@register_event_handler(plugin_id, Event.CHAT_MESSAGE_RECEIVED)
async def on_chat_message(msg: ChatMessage) -> None:
    """Handles AI prompts from incoming and synced messages."""
    if msg.type != MessageType.CHAT:
        return

    prompt: str | None
    should_process: bool
    prompt, should_process = _extract_gemini_prompt(msg)
    if not should_process:
        return

    await process_gemini_message(msg, prompt)


@register_command("gemini", "addctx",
                  "Adds the current prompt or history entries (by index) to the context for the next AI response.\n    Params: [<index1>,<index2>,...]")
async def cmd_add_ctx(chat_id: str, params: list[str], prompt: str | None = None) -> tuple[str, list[str]]:
    """Saves prompt and history entries as context for the next Gemini call."""
    context: list[str] = gemini.get_chat_context(chat_id)
    saved_count = 0

    # Process parameters (history indices)
    if chat_id in CHAT_HISTORY:
        history: deque[ChatMessage] = CHAT_HISTORY[chat_id]
        for p in params:
            try:
                idx = int(p)
                if 1 <= idx <= 10 and idx < len(history):
                    context.append(str(history[-(idx + 1)]))
                    saved_count += 1
            except ValueError:
                pass

    if prompt:
        context.append(prompt)
        saved_count += 1

    return f"💾 Context saved ({saved_count} items). Will be used in next call.", []


@register_command("gemini", "lsctx",
                  "Lists the currently active context items.")
async def cmd_ls_ctx(chat_id: str, params: list[str], prompt: str | None) -> tuple[str, list[str]]:
    """Lists the currently saved context for the chat."""
    context: list[str] = gemini.get_chat_context(chat_id)
    if len(context) == 0:
        return "ℹ️ No context is currently saved for this chat.", []

    response_lines: list[str] = ["📝 Current Context:"]
    for i, item in enumerate(context, 1):
        # Get first 5 words and add "..." if longer
        words: list[str] = item.split()
        snippet: str = " ".join(words[:5])
        if len(words) > 5:
            snippet += "..."
        response_lines.append(f"{i}. {snippet}")

    return "\n".join(response_lines), []


@register_command("gemini", "clrctx",
                  "Clears the current context.")
async def cmd_clear_ctx(chat_id: str, params: list[str], prompt: str | None) -> tuple[str, list[str]]:
    """Deletes all context for the current chat."""
    context: list[str] = gemini.get_chat_context(chat_id)
    if len(context) == 0:
        return "ℹ️ No context to clear.", []
    context.clear()
    return "🗑️ Context cleared.", []


@register_command("gemini", "lsfilestore",
                  "Lists the content of the Gemini File Search Store.")
async def cmd_ls_file_store(chat_id: str, params: list[str], prompt: str | None) -> tuple[str, list[str]]:
    response_lines: list[str] = [
        f"📂 Gemini's File Store for chat '{chat_id}':"]

    store: types.FileSearchStore | None = gemini.get_chat_store(chat_id)

    if not store:
        response_lines.append(
            "  (No active store in memory - send a message to initialize)")
    elif not store.name:
        response_lines.append("  (Store has no name)")
    else:
        try:
            remote_files: list[str] = []
            pager: Pager[types.Document] = gemini.client.file_search_stores.documents.list(
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


@register_command("gemini", "syncstore",
                  "Updates the Gemini File Search Store.")
async def cmd_sync_store(chat_id: str, params: list[str], prompt: str | None) -> tuple[str, list[str]]:
    store: types.FileSearchStore | None = gemini.get_chat_store(chat_id)
    if not store or not store.name:
        return f"❌ No remote store initialized for chat {chat_id}.", []

    chat_dir: str = get_safe_chat_dir(settings.file_store_path, chat_id)
    if not os.path.isdir(chat_dir):
        return f"❌ No local file directory found for chat {chat_id}.", []

    files: list[str] = get_local_files(chat_id)
    if not files:
        return "⚠️ Local folder is empty.", []

    uploaded_count = 0
    try:
        for filename in files:
            full_path: str = os.path.join(chat_dir, filename)
            logger.info(f"Uploading {filename} to store {store.name}...")

            # Note: Check if upload_to_file_search_store is blocking or async.
            # If it's blocking (standard sync client), wrap it in to_thread:
            # await asyncio.to_thread(gemini.client.file_search_stores.upload_to_file_search_store, ...)
            # Assuming standard SDK here:

            upload_op: types.UploadToFileSearchStoreOperation = gemini.client.file_search_stores.upload_to_file_search_store(
                file_search_store_name=store.name,
                file=full_path
            )

            # Wait for processing
            while not upload_op.done:
                logger.debug(f"Waiting for {filename} processing...")
                # CRITICAL FIX: Non-blocking sleep
                await asyncio.sleep(2)
                upload_op = gemini.client.operations.get(upload_op)

            uploaded_count += 1

    except Exception as e:
        logger.error(f"Sync failed for {chat_id}: {e}", exc_info=True)
        return f"❌ Sync error: {e}", []

    return f"🔄 Synced {uploaded_count} files to Gemini Store.", []


@register_command("gemini", "savesys", "Sets a custom system instruction for this chat. Empty to reset.")
async def cmd_save_sys(chat_id: str, params: list[str], prompt: str | None) -> tuple[str, list[str]]:
    """Saves a custom system instruction for the current chat."""
    if not prompt:
        if chat_id in custom_sys_instructions:
            del custom_sys_instructions[chat_id]
            save_sys_instructions()
            return "🗑️ Custom system instruction removed. Using default.", []
        return "ℹ️ No custom system instruction was set.", []

    custom_sys_instructions[chat_id] = prompt
    save_sys_instructions()
    return "💾 Custom system instruction saved.", []


def initialize() -> None:
    load_sys_instructions()
