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
from plugin_manager import register_action, register_command
from state import CHAT_HISTORY
from utils import get_local_files, get_safe_chat_dir, update_chat_history

logger: logging.Logger = logging.getLogger(__name__)


@dataclass
class MessageContext:
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
                model=settings.gemini_model_name,
                contents=types.Content(parts=parts),
                config=types.GenerateContentConfig(
                    system_instruction=settings.system_instruction,
                    tools=tools,
                    safety_settings=self._safety_settings,
                ),
            )
            return response.text if response.text else "🤖 (No text returned)"

        except Exception as e:
            logger.error(f"Gemini API Error: {e}", exc_info=True)
            return f"⚠️ Error querying Gemini: {str(e)}"


gemini = GeminiProvider(api_key=settings.gemini_api_key)


def extract_message_context(data: dict[str, Any]) -> MessageContext | None:
    """Parses the raw signal-cli envelope into a MessageContext."""
    envelope: dict[str, Any] = data.get("params", {}).get("envelope", {})
    source: str | None = envelope.get("source")

    if not source:
        return None

    # Determine payload type
    msg_payload: dict[str, Any] | None = envelope.get("dataMessage") or envelope.get(
        "syncMessage", {}).get("sentMessage")
    if not msg_payload:
        return None

    # Extract basic info
    body: str = msg_payload.get("message", "")
    group_info: dict[str, Any] = msg_payload.get("groupInfo", {})
    group_id: str | None = group_info.get("groupId")
    quote: str | None = msg_payload.get("quote", {}).get("text")

    # Extract attachments
    attachments: list[Attachment] = []
    for att in msg_payload.get("attachments", []):
        attachments.append(Attachment(
            content_type=att.get("contentType", "unknown"),
            id=att.get("id", ""),
            size=att.get("size", 0),
            filename=att.get("filename"),
            width=att.get("width"),
            height=att.get("height"),
            caption=att.get("caption")
        ))

    return MessageContext(
        source=source,
        chat_id=group_id if group_id else source,
        body=body,
        group_id=group_id,
        quote=quote,
        attachments=attachments
    )


async def action_send_to_gemini(data: dict[str, Any]) -> bool:
    """Handles AI prompts."""
    ctx: MessageContext | None = extract_message_context(data)
    if not ctx or not ctx.has_content:
        return False

    # Check Prefixes
    clean_msg: str = ctx.body.strip()
    prompt: str | None = None

    # Sort triggers by length to match longest first ("!gemini" before "!")
    for tw in sorted(settings.trigger_words, key=len, reverse=True):
        if clean_msg.startswith(tw):
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
    if prompt is None and not ctx.attachments:
        return False

    # Log to local history
    update_chat_history(ctx.chat_id, ctx.source, ctx.body, ctx.attachments)

    # Append quote to prompt if it exists
    full_prompt: str = prompt or ""
    if ctx.quote:
        full_prompt = f"{full_prompt}\n\n>> {ctx.quote}"

    logger.info(
        f"Processing Gemini request from {ctx.source} in {ctx.chat_id}")

    if not full_prompt and not ctx.attachments:
        response_text = "🤖 Beep Boop. Please provide a prompt."
    else:
        # Note: We aren't sending attachments to Gemini in get_response yet.
        # If your GeminiProvider supports images, pass ctx.attachments there.
        response_text: str = await gemini.get_response(ctx.chat_id, full_prompt)

    update_chat_history(ctx.chat_id, "Assistant", response_text)
    if ctx.group_id:
        await send_signal_group_message(response_text, ctx.group_id)
    else:
        await send_signal_direct_message(response_text, ctx.source)
    return True


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
                if 1 <= idx <= 10 and idx <= len(history):
                    # 1-based index from end: 1 -> -1 (most recent)
                    # skip the last history entry which is the command itself
                    # therefore the -1
                    context.append(str(history[-idx-1]))
                    saved_count += 1
            except ValueError:
                pass

    if prompt:
        context.append(prompt)
        saved_count += 1

    return f"💾 Context saved ({saved_count} items). Will be used in next call.", []


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


async def cmd_clear_ctx(chat_id: str, params: list[str], prompt: str | None) -> tuple[str, list[str]]:
    """Deletes all context for the current chat."""
    context: list[str] = gemini.get_chat_context(chat_id)
    if len(context) == 0:
        return "ℹ️ No context to clear.", []
    context.clear()
    return "🗑️ Context cleared.", []


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

register_command("gemini", "addctx", cmd_add_ctx,
                 "Adds the current prompt or history entries (by index) to the context for the next AI response.\n    Params: [<index1>,<index2>,...]")
register_command("gemini", "lsctx", cmd_ls_ctx,
                 "Lists the currently active context items.")
register_command("gemini", "clrctx", cmd_clear_ctx,
                 "Clears the current context.")
register_command("gemini", "lsfilestore", cmd_ls_file_store,
                 "Lists the content of the Gemini File Search Store.")
register_command("gemini", "syncstore", cmd_sync_store,
                 "Updates the Gemini File Search Store.")
register_action(
    "gemini",
    name="Handle Gemini in Sync Message",
    jsonpath="$.params.envelope.syncMessage.sentMessage.message",
    filter=lambda match: match.value and match.value.strip(
        ).startswith(tuple(settings.trigger_words)),  # nopep8
    handler=action_send_to_gemini,
    priority=Priority.HIGH,
)
register_action(
    "gemini",
    name="Handle Gemini in Data Message",
    jsonpath="$.params.envelope.dataMessage.message",
    filter=lambda match: match.value and match.value.strip(
        ).startswith(tuple(settings.trigger_words)),  # nopep8
    handler=action_send_to_gemini,
    priority=Priority.HIGH,
)
