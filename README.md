# Pothead

Pothead is a bot that uses `signal-cli` to interact with the Signal messaging service. It is designed to be extensible through a plugin system.

## Features

- **Signal Integration:** Communicates using `signal-cli` to send and receive Signal messages.
- **Command Processing:** Can understand and execute commands prefixed with trigger words.
- **Plugin System:** Extend the bot's functionality by creating plugins.
- **Event-driven:** Responds to system events like startup, shutdown, and a periodic timer.


## Dependencies

- `google-genai>=0.0.1`
- `pydantic-settings`
- `jsonpath_ng`
- `signal-cli`


## Installation

```bash
git clone https://github.com/flurl/pothead.git
cd pothead
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

You also need `signal-cli` https://github.com/AsamK/signal-cli and  the `libsignal-client` library https://github.com/AsamK/signal-cli/wiki/Provide-native-lib-for-libsignal 
If you're on x86 you can propably use a precompiled package but on a Raspberry Pi I had to do the following:

```bash
sudo apt install default-jdk cmake libclang-dev protobuf-compiler
# install rust
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
git clone https://github.com/signalapp/libsignal.git
cd libsignal/java
./build_jni.sh desktop
./gradlew --no-daemon :client:assemble -PskipAndroid=true
cd ../..
git clone https://github.com/AsamK/signal-cli.git
cd signal-cli
./gradlew -Plibsignal_client_path="/home/flurl/bin/pothead/libsignal/java/client/build/libs/libsignal-client-0.86.11.jar" build
./gradlew -Plibsignal_client_path="/home/flurl/bin/pothead/libsignal/java/client/build/libs/libsignal-client-0.86.11.jar" installDist
```

After that you should find the `signal-cli` script under `signal-cli/build/install/signal-cli/bin/signal-cli`.

Finally you must link `signal-cli` to your signal account - see https://github.com/AsamK/signal-cli/wiki/Linking-other-devices-(Provisioning). 


## Configuration

The bot is configured through the `pothead.toml` file or by setting environment variables.

| Variable                  | TOML setting              | Description                                      | Default                               |
| ------------------------- | ------------------------- | ------------------------------------------------ | ------------------------------------- |
| `POTHEAD_SIGNAL_CLI_PATH`   | `signal_cli_path`         | Path to your signal-cli executable               | `signal-cli/signal-cli` |
| `POTHEAD_SIGNAL_ATTACHMENTS_PATH` | `signal_attachments_path` | Path to signal-cli's attachments directory | `~/.local/share/signal-cli/attachments` |
| `POTHEAD_TRIGGER_WORDS`   | `trigger_words`           | Words to trigger the bot                         | `["!pot", "!pothead", "!ph"]`           |
| `POTHEAD_FILE_STORE_PATH`   | `file_store_path`         | Path to store documents                          | `document_store`                      |
| `POTHEAD_HISTORY_MAX_LENGTH`| `history_max_length`      | Max length of chat history                       | `30`                                  |
| `POTHEAD_LOG_LEVEL`         | `log_level`               | Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL) | `INFO`                                |
| `POTHEAD_ENABLED_PLUGINS`   | `enabled_plugins`         | A list of plugins to load.                       | `[]`                                  |


## Usage

To run the bot, execute the main script:

```bash
python pothead.py
```

## Testing

To run the tests, use the provided script which sets up the necessary environment variables:

```bash
./run_tests.sh
```

## Plugins

Pothead supports a plugin architecture to extend its functionality. To create a plugin, you need to create a directory in the `plugins` folder with a `main.py` and a `manifest.toml` file.

### Plugin Configuration

Each plugin can have its own configuration. Plugins should look for a `config.toml` file within their directory (e.g., `plugins/myplugin/config.toml`). This allows for modular configuration management.

### Available Plugins

Pothead comes with several built-in plugins. Each plugin has its own documentation in its respective directory:

- [**AI Autoresponder**](plugins/ai_autoresponder/README.md): Automatically responds to messages in specific chats using AI.
- [**Cron**](plugins/cron/README.md): Provides a scheduling service for other plugins.
- [**Echo**](plugins/echo/README.md): A simple utility plugin that echoes messages back.
- [**FileSender**](plugins/filesender/README.md): Schedules the sending of text file contents.
- [**Gemini**](plugins/gemini/README.md): Integrates with Google's Gemini AI for chat and RAG.
- [**Welcome**](plugins/welcome/README.md): Sends welcome messages to new group members.

To enable a plugin, add its name to the `enabled_plugins` list in `pothead.toml`.

For more details on each plugin, please refer to their individual README files. The [**Echo**](plugins/echo/README.md) plugin is a good starting point for learning how to build your own plugins.
