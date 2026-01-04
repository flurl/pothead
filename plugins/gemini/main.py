
import logging
from collections import deque
import os
import time
from typing import Any, cast

from config import settings
from google.genai.client import Client
from google.genai import types
from google.genai.pagers import Pager

from datatypes import Attachment, ChatMessage, Priority
from messaging import send_signal_message
from plugin_manager import register_action, register_command
from state import CHAT_HISTORY
from utils import get_local_files, get_safe_chat_dir, update_chat_history

logger: logging.Logger = logging.getLogger(__name__)


class GeminiProvider:
    def __init__(self, api_key: str) -> None:
        self._client: Client = Client(api_key=api_key)
        self._chat_stores: dict[str, types.FileSearchStore] = {}
        self._chat_contexts: dict[str, list[str]] = {}

    @property
    def client(self) -> Client:
        return self._client

    async def get_response(self, chat_id: str, prompt_text: str) -> str | None:
        """Sends text to Gemini and returns the response."""
        try:
            chat_store: types.FileSearchStore | None = self.get_chat_store(
                chat_id)

            parts: list[types.Part] = []
            # Add context if available and withdraw it
            context: list[str] = self.get_chat_context(chat_id)
            if len(context) > 0:
                for ctx in context:
                    parts.append(types.Part(text=ctx))
                context.clear()

            # Add prompt
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
            response: types.GenerateContentResponse = await self.client.aio.models.generate_content(  # type: ignore
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
                    ],
                ),
            )
            return response.text
        except Exception as e:
            return f"Error querying Gemini: {str(e)}"

    def get_chat_store(self, chat_id: str) -> types.FileSearchStore | None:
        if chat_id in self._chat_stores:
            return self._chat_stores[chat_id]

        logger.info(f"Creating file store for chat {chat_id}...")
        try:
            new_store: types.FileSearchStore = self._client.file_search_stores.create(
                config={"display_name": chat_id})

            if not new_store or not new_store.name:
                return None

            self._chat_stores[chat_id] = new_store
            return new_store
        except Exception as e:
            logger.error(f"Failed to create store for {chat_id}: {e}")
            return None

    def get_chat_context(self, chat_id: str) -> list[str]:
        if chat_id not in self._chat_contexts:
            self._chat_contexts[chat_id] = []
        return self._chat_contexts[chat_id]


gemini = GeminiProvider(api_key=settings.gemini_api_key)


async def action_send_to_gemini(data: dict[str, Any]) -> None:
    """Handles AI prompts."""
    params: dict[str, Any] = data.get("params", {})
    envelope: dict[str, Any] = params.get("envelope", {})

    # 1. Extract source
    source: str | None = envelope.get("source")
    if source is None:
        logger.error("No source found in envelope.")
        return

    # 2. Extract Message Body and Context (Group vs Direct)
    message_body: str | None = None
    group_id: str | None = None
    quote: str | None = None
    attachments: list[Attachment] = []

    msg_payload: dict[str, Any] | None = None
    if "dataMessage" in envelope:
        msg_payload = envelope.get("dataMessage")
    elif "syncMessage" in envelope:
        msg_payload = envelope.get("syncMessage", {}).get("sentMessage")

    if msg_payload:
        message_body = msg_payload.get("message")
        if "groupInfo" in msg_payload:
            group_id = msg_payload["groupInfo"].get("groupId")
        if "quote" in msg_payload:
            quote = msg_payload["quote"].get("text")
        if "attachments" in msg_payload:
            for att in msg_payload["attachments"]:
                attachments.append(Attachment(
                    content_type=att.get("contentType", "unknown"),
                    id=att.get("id", ""),
                    size=att.get("size", 0),
                    filename=att.get("filename"),
                    width=att.get("width"),
                    height=att.get("height"),
                    caption=att.get("caption")
                ))

    if not message_body and not attachments:
        return

    # 3. Check Prefixes
    clean_msg: str = message_body.strip() if message_body else ""
    prompt: str | None = None

    settings.trigger_words.sort(key=len, reverse=True)
    for tw in settings.trigger_words:
        if clean_msg.startswith(tw):
            content: str = clean_msg[len(tw):].strip()
            if content.startswith("#"):
                return
            else:
                prompt = content
            break

    if prompt is None and not attachments:
        return

    chat_id: str = group_id if group_id else source
    update_chat_history(chat_id, source, message_body, attachments)

    if quote is not None:
        prompt = f"{prompt}\n\n{quote}" if prompt else quote

    logger.info(
        f"Processing request from {source} (Group: {group_id}): {prompt}")

    if not prompt:
        response_text = "🤖 Beep Boop. Please provide a prompt."
    else:
        response_text: str | None = await gemini.get_response(chat_id, prompt)

    if response_text is None:
        response_text = "🤖 Beep Boop. Something went wrong."

    update_chat_history(chat_id, "Assistant", response_text)

    await send_signal_message(source, response_text, group_id)
    logger.info(f"Sent response to {source}")


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
    # Update Gemini Store
    # Invalidate cache and delete old store to force re-upload
    store: types.FileSearchStore | None = gemini.get_chat_store(chat_id)

    if store is None or not store.name:
        logger.info(f"No remote store found for chat {chat_id}.")
        return f"❌ No remote store found for chat {chat_id}.", []

    chat_dir: str = get_safe_chat_dir(settings.file_store_path, chat_id)
    if not os.path.isdir(chat_dir):
        logger.info(f"No file store found for chat {chat_id}.")
        return f"❌ No file store found for chat {chat_id}.", []

    files: list[str] = get_local_files(chat_id)
    if not files:
        return f"No files found for syncing", []

    try:
        for filename in files:
            full_path: str = os.path.join(chat_dir, filename)
            logger.info(f"Uploading {full_path}...")
            upload_op = gemini.client.file_search_stores.upload_to_file_search_store(
                file_search_store_name=store.name,
                file=full_path
            )
            while not upload_op.done:
                logger.info(f"Waiting for {filename}...")
                time.sleep(2)
                upload_op: types.UploadToFileSearchStoreOperation = gemini.client.operations.get(
                    upload_op)

    except Exception as e:
        logger.error(f"Failed to sync stores for {chat_id}: {e}")
        return f"❌ Failed to sync stores for {chat_id}: {e}", []

    return f"🔄 Gemini File Search Store synced.", []


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
    filter=lambda msg: msg.strip().startswith(tuple(settings.trigger_words)),
    handler=action_send_to_gemini,
    priority=Priority.HIGH,
    halt=True
)
register_action(
    "gemini",
    name="Handle Gemini in Data Message",
    jsonpath="$.params.envelope.dataMessage.message",
    filter=lambda msg: msg.strip().startswith(tuple(settings.trigger_words)),
    handler=action_send_to_gemini,
    priority=Priority.HIGH,
    halt=True
)
