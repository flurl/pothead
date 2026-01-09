# Pothead

Pothead is a bot that uses `signal-cli` to interact with the Signal messaging service. It is designed to be extensible through a plugin system.

## Features

- **Signal Integration:** Communicates using `signal-cli` to send and receive Signal messages.
- **Command Processing:** Can understand and execute commands prefixed with trigger words.
- **Plugin System:** Extend the bot's functionality by creating plugins.
- **Event-driven:** Responds to system events like startup, shutdown, and a periodic timer.

## Configuration

The bot is configured through the `pothead.toml` file or by setting environment variables.

| Variable                  | TOML setting              | Description                                      | Default                               |
| ------------------------- | ------------------------- | ------------------------------------------------ | ------------------------------------- |
| `POTHEAD_SIGNAL_CLI_PATH`   | `signal_cli_path`         | Path to your signal-cli executable               | `signal-cli/signal-cli` |
| `POTHEAD_SIGNAL_ATTACHMENTS_PATH` | `signal_attachments_path` | Path to signal-cli's attachments directory | `~/.local/share/signal-cli/attachments` |
| `POTHEAD_GEMINI_MODEL_NAME` | `gemini_model_name`       | Gemini model name                                | `gemini-2.5-flash`                      |
| `POTHEAD_TRIGGER_WORDS`   | `trigger_words`           | Words to trigger the bot                         | `["!pot", "!pothead", "!ph"]`           |
| `POTHEAD_FILE_STORE_PATH`   | `file_store_path`         | Path to store documents                          | `document_store`                      |
| `POTHEAD_HISTORY_MAX_LENGTH`| `history_max_length`      | Max length of chat history                       | `30`                                  |
| `POTHEAD_LOG_LEVEL`         | `log_level`               | Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL) | `INFO`                                |
| `POTHEAD_SYSTEM_INSTRUCTION`| `system_instruction`      | The system instruction for the bot.              | `Du bist POT-HEAD...`                 |
| `POTHEAD_PLUGINS`           | `plugins`                 | A list of plugins to load.                       | `["gemini", "welcome", "cron", "filesender"]` |


## Dependencies

- `google-genai>=0.0.1`
- `pydantic-settings`
- `jsonpath_ng`

## Usage

To run the bot, execute the main script:

```bash
python pothead.py
```

## Plugins

Pothead supports a plugin architecture to extend its functionality. To create a plugin, you need to create a directory in the `plugins` folder with a `main.py` and a `manifest.toml` file.

### Enabled Plugins

The following plugins are enabled by default:

- `gemini`: Interacts with the Google Gemini model.
- `welcome`: Sends a welcome message to new users.
- `cron`: Schedules tasks to run at a specific time.
- `filesender`: Sends files to users.

For more details on each plugin, please refer to the plugin's source code. The `echo` plugin may be a good starting point.
