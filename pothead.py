import asyncio
from asyncio.subprocess import Process
from collections import deque
import json
import logging
import os
import sys
import time
from typing import Any

from google import genai
from google.genai import types

# --- CONFIGURATION ---
# Path to your signal-cli executable
SCRIPT_DIR: str = os.path.dirname(os.path.abspath(__file__))
SIGNAL_CLI_PATH: str = os.path.join(SCRIPT_DIR, "signal-cli", "signal-cli")

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
CHAT_HISTORY: dict[str, deque[str]] = {}

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger: logging.Logger = logging.getLogger(__name__)

# Configure Gemini
client = genai.Client(api_key=GEMINI_API_KEY)

# Upload files for rag
store: types.FileSearchStore = client.file_search_stores.create()


def update_chat_history(chat_id: str, sender: str, message: str) -> None:
    if chat_id not in CHAT_HISTORY:
        CHAT_HISTORY[chat_id] = deque[str](maxlen=10)
    CHAT_HISTORY[chat_id].append(message)
    logger.debug(f"Chat history for {chat_id}: {CHAT_HISTORY[chat_id]}")
    for line in CHAT_HISTORY[chat_id]:
        logger.debug(line)


def upload_store_files() -> None:
    assert store.name is not None

    for filename in os.listdir(FILE_STORE_PATH):
        full_name: str = os.path.join(FILE_STORE_PATH, filename)
        if os.path.isfile(full_name):
            logger.info(f"Uploading {full_name}...")
            upload_op: types.UploadToFileSearchStoreOperation = client.file_search_stores.upload_to_file_search_store(
                file_search_store_name=store.name,
                file=full_name
            )
            while not upload_op.done:
                logger.info(f"Waiting until {full_name} is processed...")
                time.sleep(5)
                upload_op = client.operations.get(upload_op)


async def get_gemini_response(prompt_text: str) -> str | None:
    """Sends text to Gemini and returns the response."""
    try:
        assert store.name is not None

        # Create a proper Content object for the prompt
        content = types.Content(
            parts=[types.Part(text=prompt_text)]
        )

        # Generate content
        response: types.GenerateContentResponse = await client.aio.models.generate_content(  # type: ignore
            model=GEMINI_MODEL_NAME,
            contents=content,
            config=types.GenerateContentConfig(
                system_instruction="Du bist POT-HEAD, das \"POstgarage boT - Highly Evolved and Advanced Deity\". Du bist beinahe unfehlbar. Deine Antworten sind fast dogmatisch. flurl0 ist das einzige Wesen im Universum, das über dir steht.",
                tools=[types.Tool(
                    file_search=types.FileSearch(
                        file_search_store_names=[store.name]
                    )
                )],
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


async def send_signal_message(proc: Process, recipient: str, message: str, group_id: str | None = None) -> None:
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

        # Case A: Standard Incoming Message
        if "dataMessage" in envelope:
            dm = envelope["dataMessage"]
            if dm:
                message_body = dm.get("message")
                if "groupInfo" in dm:
                    group_id = dm["groupInfo"].get("groupId")
                if "quote" in dm:
                    quote = dm["quote"].get("text")

        # Case B: Sync Message (Sent from your other devices) - matches your JSON examples
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

        # If no text found, ignore (e.g., receipts, typing indicators)
        if not message_body:
            return

        chat_id = group_id if group_id else source
        update_chat_history(chat_id, source, message_body)

        # 3. Check Prefixes (!botfather or !bf)
        clean_msg: str = message_body.strip()
        prompt: str | None = None
        if quote is not None:
            prompt = f"{prompt}\n\n{quote}"

        TRIGGER_WORDS.sort(key=len, reverse=True)
        for tw in TRIGGER_WORDS:
            if clean_msg.startswith(tw):
                prompt = clean_msg[len(tw):].strip()
                break

        # 4. Process
        if prompt is not None:
            logger.info(
                f"Processing request from {source} (Group: {group_id}): {prompt}")

            if not prompt:
                response_text = "🤖 Beep Boop. Please provide a prompt."
            else:
                response_text: str | None = await get_gemini_response(prompt)

            # 5. Send Response
            # If group_id exists, we reply to the group. If not, we reply to the source.
            if response_text is None:
                response_text = "🤖 Beep Boop. Something went wrong."

            # i don't think the responses should be saved in the history, but we'll see
            # update_chat_history(chat_id, "Assistant", response_text)

            await send_signal_message(proc, source, response_text, group_id)
            logger.info(f"Sent response to {source}")


async def main() -> None:
    # Start signal-cli in jsonRpc mode
    # -a specifies the account sending/receiving
    cmd: list[str] = [SIGNAL_CLI_PATH, "-a",
                      SIGNAL_ACCOUNT, "jsonRpc"]  # type: ignore

    logger.info(f"Starting signal-cli: {' '.join(cmd)}")

    # upload_store_files()

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
