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
import logging
import os
from collections import deque
from dataclasses import dataclass
from typing import Any, cast

from config import settings
from google.genai.client import Client
from google.genai import types
from google.genai.pagers import Pager

from datatypes import Attachment, ChatMessage, Priority
from messaging import send_signal_direct_message, send_signal_group_message
from plugin_manager import get_plugin_settings, register_action, register_command
from state import CHAT_HISTORY
from utils import get_local_files, get_safe_chat_dir, update_chat_history

logger: logging.Logger = logging.getLogger(__name__)

plugin_id: str = "gemini"

from plugins.gemini.config import PluginSettings  # nopep8
plugin_settings: PluginSettings = cast(
    PluginSettings, get_plugin_settings(plugin_id))


@dataclass
class MessageCotext:
    """Standardized representation of an incoming message."""
    source: str
    chat_id: str
    body: str
    group_id: str | None = None
    quote: str | None = None
    attachments: list[Attachment] | None = None

    @property
    def has_content(self) -> bool:
        return bool(self.body or (self.attachments and len(self.attachments) > 0))


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

    async def get_response(self, chat_id: str, prompt_text: str) -> str:
        """Sends text to Gemini and returns the response."""
        try:
            parts: list[types.Part] = []

            # Inject and consume context
            context_list: list[str] = self.get_chat_context(chat_id)
            if context_list:
                parts.extend([types.Part(text=ctx) for ctx in context_list])
                context_list.clear()  # Clear after usage as per original logic

            parts.append(types.Part(text=prompt_text))

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

            # Async Generation
            response: types.GenerateContentResponse = await self.client.aio.models.generate_content(  # type: ignore
                model=plugin_settings.gemini_model_name,
                contents=types.Content(parts=parts),
                config=types.GenerateContentConfig(
                    system_instruction=plugin_settings.system_instruction,
                    tools=tools,
                    safety_settings=self._safety_settings,
                ),
            )
            return response.text if response.text else "🤖 (No text returned)"

        except Exception as e:
            logger.error(f"Gemini API Error: {e}", exc_info=True)
            return f"⚠️ Error querying Gemini: {str(e)}"


gemini = GeminiProvider(api_key=plugin_settings.gemini_api_key)


@register_action(
    "gemini",
    name="Handle Gemini in Sync Message",
    jsonpath="$.params.envelope.syncMessage.sentMessage.message",
    filter=lambda match: match.value and match.value.strip(
    ).upper().startswith(tuple(w.upper() for w in settings.trigger_words)),
    priority=Priority.HIGH,
)
@register_action(
    "gemini",
    name="Handle Gemini in Data Message",
    jsonpath="$.params.envelope.dataMessage.message",
    filter=lambda match: match.value and match.value.strip(
    ).upper().startswith(tuple(w.upper() for w in settings.trigger_words)),
    priority=Priority.HIGH,
)
async def action_send_to_gemini(data: dict[str, Any]) -> bool:
    """Handles AI prompts."""
    # ctx: MessageContext | None = extract_message_context(data)
    msg: ChatMessage | None = ChatMessage.from_json(data)
    if not msg:
        return False

    # Check Prefixes
    clean_msg: str = msg.text and msg.text.strip() or ""
    prompt: str | None = None

    # Sort triggers by length to match longest first ("!gemini" before "!")
    for tw in sorted(settings.trigger_words, key=len, reverse=True):
        if clean_msg.upper().startswith(tw.upper()):
            content: str = clean_msg[len(tw):].strip()
            # Ignore commands notes starting with #
            if content.startswith("#"):
                return False
            prompt = content
            break

    # If no prompt text and no attachments (and we are here), it might just be a matched prefix with empty body?
    # Logic: If prompt is None here, it means the message didn't start with a trigger word.
    # However, the filter in register_action should have caught this.
    # We handle the case where it's ONLY a trigger word.
    if prompt is None and not msg.attachments:
        return False

    # Log to local history
    # update_chat_history(ctx.chat_id, ctx.source, ctx.body, ctx.attachments)

    # Append quote to prompt if it exists
    full_prompt: str = prompt or ""
    if msg.quote and msg.quote.text:
        full_prompt = f"{full_prompt}\n\n>> {msg.quote.text}"

    logger.info(
        f"Processing Gemini request from {msg.source} in {msg.chat_id}")

    if not full_prompt and not msg.attachments:
        response_text = "🤖 Beep Boop. Please provide a prompt."
    else:
        # Note: We aren't sending attachments to Gemini in get_response yet.
        # If your GeminiProvider supports images, pass ctx.attachments there.
        response_text: str = await gemini.get_response(msg.chat_id, full_prompt)

    update_chat_history(ChatMessage(source="Assistant",
                        destination=msg.chat_id, text=response_text))
    if msg.group_id:
        await send_signal_group_message(response_text, msg.group_id)
    else:
        # For direct messages, the recipient of the reply is the original source
        await send_signal_direct_message(response_text, msg.source)
    return True


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
