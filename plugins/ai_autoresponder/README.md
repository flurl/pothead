# AI Autoresponder Plugin

This plugin automatically responds to incoming messages in specific Signal chats using the AI service (typically provided by the `gemini` plugin).

## Features

- **Automated Responses:** Automatically forwards messages from enabled chats to the AI and sends back the generated response.
- **Message Loop Prevention:** Ignores messages for a configurable amount of time after the bot's signal account has sent a message (from another device, possible human interaction).
- **Persistence:** Maintains a list of enabled chat IDs in `auto_chat_ids.txt`.

## Commands

- `!ph#autoenable`: Enables the autoresponder for the current chat.
- `!ph#autodisable`: Disables the autoresponder for the current chat.

## Configuration

The plugin uses the following settings (configurable via `config.toml` or environment variables):

- `auto_chat_ids`: A list of chat IDs where the autoresponder is active.
- `wait_after_message_from_self`: Time in seconds to ignore messages after the bot's signal account has sent a message (default: 30 seconds).

## Dependencies

- Requires a plugin that provides the `send_to_ai` service (e.g., the `gemini` plugin).
