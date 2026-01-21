# Gemini Plugin

The Gemini plugin integrates Pothead with the Google Gemini API, providing advanced AI capabilities.

## Features

- **AI Chat:** Interact with Gemini by starting messages with a trigger word (e.g., `!ph Hello AI`).
- **Image Understanding:** Attach images to your messages, and Gemini will analyze them (multimodal capabilities).
- **Context Management:** Save message history or specific prompts into a temporary context for multi-turn conversations.
- **File Search Store (RAG):** Synchronize local documents with Gemini's File Search Store to allow the AI to retrieve information from them (Retrieval-Augmented Generation).

## Commands

- `!ph#addctx [<index1>,<index2>,...]`: Adds history entries (by index from the bottom) or the trailing prompt to the context for the next AI call.
- `!ph#lsctx`: Lists currently saved context items.
- `!ph#clrctx`: Clears the current context.
- `!ph#lsfilestore`: Lists files currently in Gemini's remote File Search Store for the chat.
- `!ph#syncstore`: Uploads local files from the bot's file store for the chat to Gemini's remote store.

## Configuration

- `gemini_api_key`: Your Google Gemini API key.
- `gemini_model_name`: The Gemini model to use.
- `system_instruction`: Instructions that guide the AI's behavior.
- `context_expiry_threshold`: (Default: 300) The number of seconds of inactivity after which a conversation context is considered expired. Used by `chat_with_ai` to determine how much history to send.

## AI Chat

Any message that starts with a trigger word (like `!ph`) and is NOT followed by a command (starting with `#`) will be sent directly to the Gemini AI. If the message quotes another message, that quoted text is also included in the prompt. You can also attach images to your message, and they will be included in the request to Gemini.

## File Storage

Local files for RAG should be placed in the directory specified by `POTHEAD_FILE_STORE_PATH`, under a subdirectory named after the chat ID.

## Services

This plugin exposes services that can be used by other plugins:

- **`send_to_ai`**: Sends a specific message (and its attachments/quotes) to Gemini. This is used for direct interactions (e.g., trigger words).
- **`chat_with_ai`**: Sends the recent chat history to Gemini. This is useful for auto-responders or conversational bots. It uses the `context_expiry_threshold` to determine where the current conversation context starts.
