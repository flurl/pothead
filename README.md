# Pothead

Pothead is a bot that uses `signal-cli` to interact with the Signal messaging service. It is designed to be extensible through a plugin system.

## Features

- **Signal Integration:** Communicates using `signal-cli` to send and receive Signal messages.
- **Command Processing:** Can understand and execute commands prefixed with trigger words.
- **Plugin System:** Extend the bot's functionality by creating plugins.
- **Event-driven:** Responds to system events like startup, shutdown, and a periodic timer.

## Deployment Modes

Pothead supports two deployment modes that affect how `signal-cli` must be set up and how message fields are interpreted:

- **Shared mode** (`dedicated_account = false`, default): `signal-cli` is linked as a secondary device to an existing Signal account. Messages sent from the owner's other devices arrive as `syncMessage` with `is_synced = true`; for these, `source` is the owner's own number and `destination` is the other party. Incoming messages from other people have `source` = sender, `destination` = `null`. The `chat_id` for a DM is therefore the *other party's* number in both directions.

- **Dedicated mode** (`dedicated_account = true`): `signal-cli` is registered as its own Signal number. All incoming DMs have `source` = sender and `destination` = the bot's number. There are no synced messages. The `chat_id` for a DM is the sender's number.

This setting currently changes the behavior of the **Gemini** plugin: in shared mode it only responds to messages that start with a trigger word; in dedicated mode it responds to any message addressed directly to the bot or where the bot is @mentioned.


## Dependencies

- `google-genai>=0.0.1`
- `pydantic-settings`
- `jsonpath_ng`
- `Pillow`
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

Since https://github.com/AsamK/signal-cli/commit/32c8d4f80102623c29c81e29ae4e3cd921f48ddb `signal-cli` needs Java 25 to compile. But `signallib` does not (yet) compile with Java 25. Therefore you have to use two different Java Versions to successfully install `signal-cli` if you can't use the binary distribution of `libsignal`.

I for example downloaded OpenJDK 25 from https://jdk.java.net/25/ . And then I make it default by setting the environment variable `JAVA_HOME`:

```bash
export JAVA_HOME=/path/to/openJDK/jdk-25.0.2/
```

But then you also have to set `JAVA_HOME` to run `pothead` .

After that you should find the `signal-cli` script under `signal-cli/build/install/signal-cli/bin/signal-cli`.

Two helper scripts `install_or_update_signal-cli.sh` and `check_release.sh` are provided that should do the hard work for you. Just set `JAVA_HOME` and run `install_or_update_signal-cli.sh`. This script expects your default JDK to be suitable for compiling `libsignal` and the via `JAVA_HOME` set JDK to be suitable for compiling `signal-cli`.

Finally you must link `signal-cli` to your signal account - see https://github.com/AsamK/signal-cli/wiki/Linking-other-devices-(Provisioning). 

There's also a script `utils/install_systemd_service.sh` that can be used to install pothead as a systemd service that runs at boot. The script creates a unit file from the template `utils/pothead.service.template`. It make the service run under the current user and group.

`install_systemd_service.sh` supports one optional parameter `--java-home` which you can use to specify a directory that will be used as the `JAVA_HOME` environment variable when pothead is run.


## Configuration

The bot is configured through the `pothead.toml` file or by setting environment variables.

| Variable                  | TOML setting              | Description                                      | Default                               |
| ------------------------- | ------------------------- | ------------------------------------------------ | ------------------------------------- |
| `POTHEAD_SIGNAL_CLI_PATH`   | `signal_cli_path`         | Path to your signal-cli executable               | `signal-cli/signal-cli` |
| `POTHEAD_SIGNAL_ATTACHMENTS_PATH` | `signal_attachments_path` | Path to signal-cli's attachments directory | `~/.local/share/signal-cli/attachments` |
| `POTHEAD_DEDICATED_ACCOUNT` | `dedicated_account`       | Set to `true` if the bot has its own Signal number (see [Deployment Modes](#deployment-modes)) | `false` |
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
- [**Archiver**](plugins/archiver/README.md): Archives chat messages and attachments to persistent local storage. Enable/disable per chat with `enablearchive`/`disablearchive`. Messages are stored in rolling JSONL files; attachments are saved alongside them.
- [**Cron**](plugins/cron/README.md): Provides a scheduling service for other plugins.
- [**Echo**](plugins/echo/README.md): A simple utility plugin that echoes messages back.
- [**FileSender**](plugins/filesender/README.md): Schedules the sending of text file contents. Also provides a file-based outbox: drop `.md` files into a chat's outbox directory and they are sent automatically (use the `outboxdir` command to get the path for the current chat).
- [**Gemini**](plugins/gemini/README.md): Integrates with Google's Gemini AI for chat, image analysis, and RAG. Behavior depends on the [deployment mode](#deployment-modes): in shared mode it requires a trigger word; in dedicated mode it responds to any message addressed to the bot or where it is @mentioned.
- [**Welcome**](plugins/welcome/README.md): Sends welcome messages to new group members.

To enable a plugin, add its name to the `enabled_plugins` list in `pothead.toml`.

For more details on each plugin, please refer to their individual README files. The [**Echo**](plugins/echo/README.md) plugin is a good starting point for learning how to build your own plugins.
