
import pytest
from unittest.mock import AsyncMock, patch
from pothead import handle_command, COMMANDS
from datatypes import ChatMessage
from plugin_manager import load_plugins, PLUGIN_COMMANDS

@pytest.mark.asyncio
@patch('pothead.send_signal_message', new_callable=AsyncMock)
async def test_handle_command(mock_send_signal_message):
    """
    Tests that the handle_command function correctly processes a command
    and calls send_signal_message with the echoed text.
    """
    # Manually load plugins to populate the command list
    load_plugins()
    # It's better not to modify the global list directly, but for this test it's okay.
    # A cleaner way would be to use a fixture to manage this.
    if not any(c.name == 'ping' for c in COMMANDS):
        COMMANDS.extend(PLUGIN_COMMANDS)


    # Sample incoming message data
    incoming_data = {
        "params": {
            "envelope": {
                "source": "test", # Corresponds to POTHEAD_SUPERUSER env var
                "sourceDevice": 1,
                "timestamp": 1678886400000,
                "dataMessage": {
                    "message": "!pot #ping",
                    "timestamp": 1678886400000,
                    "groupInfo": {
                        "groupId": "group123"
                    }
                }
            }
        }
    }

    # Call the handler
    await handle_command(incoming_data)

    # Assert that send_signal_message was called
    mock_send_signal_message.assert_called_once()

    # Check the arguments it was called with
    # The first argument is the ChatMessage object
    call_args, call_kwargs = mock_send_signal_message.call_args
    sent_message = call_args[0]

    assert isinstance(sent_message, ChatMessage)
    assert sent_message.text == "Pong!"
    assert sent_message.source == "Assistant"
    assert sent_message.destination == "group123"
    assert sent_message.group_id == "group123"
