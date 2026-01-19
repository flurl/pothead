# Echo Plugin

The Echo plugin is a utility and demonstration plugin. It echoes back messages that are not bot commands and provides a few simple commands.

## Features

- **Message Echoing:** Automatically replies to any message that does not start with a trigger word (e.g., `!`) with a prefixed version of that message.
- **Service Consumption:** Demonstrates how to use the `cron` service by scheduling a periodic "heartbeat" log message.
- **Event Handling:** Sends messages to the superuser on bot startup and shutdown.

## Commands

- `!ph#ping`: Responds with "Pong!".
- `!ph#echo <prompt>`: Responds with the provided `<prompt>`.

## Configuration

- `echo_prefix`: The prefix added to echoed messages (default: "Echo:").
