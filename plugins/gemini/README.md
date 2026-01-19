# Gemini Plugin

The Gemini plugin integrates Pothead with the Google Gemini API, providing advanced AI capabilities.

## Features

- **AI Chat:** Interact with Gemini by starting messages with a trigger word (e.g., `!ph Hello AI`).
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
- `gemini_model_name`: The Gemini model to use (default: `gemini-2.0-flash`).
- `system_instruction`: Instructions that guide the AI's behavior.

## AI Chat

Any message that starts with a trigger word (like `!ph`) and is NOT followed by a command (starting with `#`) will be sent directly to the Gemini AI. If the message quotes another message, that quoted text is also included in the prompt.

## File Storage

Local files for RAG should be placed in the directory specified by `POTHEAD_FILE_STORE_PATH`, under a subdirectory named after the chat ID.
