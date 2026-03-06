# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

**Run the bot:**
```bash
python pothead.py
```

**Run all tests:**
```bash
./run_tests.sh
```

**Run a single test file:**
```bash
POTHEAD_SIGNAL_ACCOUNT="test" POTHEAD_GEMINI_API_KEY="test" POTHEAD_SUPERUSER="test" POTHEAD_ENABLED_PLUGINS='["echo", "cron", "filesender", "gemini", "welcome"]' PYTHONPATH=. venv/bin/pytest tests/test_echo_plugin.py
```

**Activate the virtual environment:**
```bash
source venv/bin/activate
```

## Configuration

The bot requires two mandatory environment variables (not in TOML):
- `POTHEAD_SIGNAL_ACCOUNT` — the Signal phone number/account
- `POTHEAD_SUPERUSER` — recipient for startup/shutdown notifications

All other settings go in `pothead.toml` (or as `POTHEAD_*` env vars). Key settings:
- `signal_cli_path` — path to the `signal-cli` binary
- `enabled_plugins` — list of plugin IDs to load (e.g. `["echo", "gemini"]`)
- `trigger_words` — default `["!pot", "!pothead", "!ph"]`

## Architecture

Pothead is an async Python bot that bridges Signal messaging (via `signal-cli`) with a plugin system.

### Core Flow

1. `pothead.py` spawns `signal-cli` as a subprocess in `jsonRpc` mode.
2. Each line of stdout from `signal-cli` is a JSON-RPC message parsed in `process_incoming_line()`.
3. The message is matched against a list of **Actions** (sorted by priority). Each `Action` has:
   - A `jsonpath` expression to locate data in the message
   - An optional `filter` callable for finer matching
   - A `handler` async function that returns `bool` (True = stop further processing)
4. System events (`POST_STARTUP`, `PRE_SHUTDOWN`, `TIMER`) are fired via `events.fire_event()`.

### Key Modules

| File | Responsibility |
|------|---------------|
| `pothead.py` | Entry point; main loop, system Actions, command dispatch |
| `datatypes.py` | All dataclasses (`ChatMessage`, `Action`, `Command`, `Event`, etc.) and `SignalMessage.from_json()` parsing |
| `plugin_manager.py` | Plugin loading, registration decorators (`register_action`, `register_command`, `register_event_handler`, `register_service`) |
| `events.py` | `EVENT_HANDLERS` registry and `fire_event()` |
| `messaging.py` | Low-level JSON-RPC sending to `signal-cli`; markdown→Signal style conversion |
| `commands.py` | Built-in system commands (`help`, `save`, `grant`, `lsstore`, etc.) |
| `config.py` | `Settings` via pydantic-settings (TOML + env vars) |
| `state.py` | Global `CHAT_HISTORY` deque and `CHAT_LOCAL_STORES` |
| `utils.py` | Helpers for permissions, chat history updates, file/attachment operations |

### Message Types

`SignalMessage.from_json()` in `datatypes.py` parses raw signal-cli envelopes into typed objects:
- `dataMessage` → `ChatMessage` (from others)
- `syncMessage.sentMessage` → `ChatMessage` (from self on other devices)
- `editMessage` → `EditMessage`
- `remoteDelete` → `DeleteMessage`
- `groupInfo.type == UPDATE` → `GroupUpdateMessage`
- `receiptMessage` / `typingMessage` → `ReceiptMessage` / `TypingMessage`

### Command Syntax

Commands are triggered by: `<trigger_word>#<command>[,param1,param2] [prompt text]`

Example: `!ph#save,1,2 some notes` — saves history entries 1 and 2 plus the prompt.

### Plugin System

Each plugin lives in `plugins/<id>/` and requires:
- `manifest.toml` — with at least an `id` field
- `main.py` — uses decorators to register functionality

Plugin registration decorators (imported from `plugin_manager`):
- `@register_action(plugin_id, name, jsonpath, priority, filter)` — react to raw JSON-RPC messages
- `@register_command(plugin_id, name, help_text)` — add a command handler; signature: `async (chat_id, params, prompt) -> tuple[str, list[str]]`
- `@register_event_handler(plugin_id, event)` — subscribe to system events; signature: `async () -> None` (some events pass a `SignalMessage` arg)
- `@register_service(service_name)` / `get_service(service_name)` — inter-plugin service registry

Optional `initialize()` function in `main.py` is called after all plugins are loaded.

Optional `config.py` with a `PluginSettings(PluginSettingsBase)` class loads from `plugins/<id>/config.toml` and `plugins/<id>/.env`.

The **echo** plugin (`plugins/echo/`) is the canonical reference implementation showing all four extension points.

### Priority

`Priority` enum: `SYS(4) > HIGH(3) > NORMAL(2) > LOW(1)`. System actions run before plugin actions. Returning `True` from a handler stops further action processing for that message.

### Pending Replies

`PENDING_REPLIES` dict in `plugin_manager.py` maps JSON-RPC request IDs to callbacks. When `signal-cli` responds to a request (identified by `id`), the callback is invoked and removed. Used by `messaging.py` to handle `send` confirmations and `listGroups` responses.
