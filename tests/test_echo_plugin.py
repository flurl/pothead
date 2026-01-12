
import pytest
from unittest.mock import AsyncMock, patch
from plugins.echo.main import echo_handler
from datatypes import ChatMessage


@pytest.mark.asyncio
@patch('plugins.echo.main.send_signal_message', new_callable=AsyncMock)
async def test_echo_handler(mock_send_signal_message):
    """
    Tests that the echo_handler correctly processes a message
    and calls send_signal_message with the echoed text.
    """
    # Sample incoming message data
    incoming_data = {
        "params": {
            "envelope": {
                "source": "+1234567890",
                "sourceDevice": 1,
                "timestamp": 1678886400000,
                "dataMessage": {
                    "message": "Hello, world!",
                    "timestamp": 1678886400000,
                    "groupInfo": {
                        "groupId": "group123"
                    }
                }
            }
        }
    }

    # Call the handler
    await echo_handler(incoming_data)

    # Assert that send_signal_message was called
    mock_send_signal_message.assert_called_once()

    # Check the arguments it was called with
    # The first argument is the ChatMessage object
    call_args, call_kwargs = mock_send_signal_message.call_args
    sent_message = call_args[0]

    assert isinstance(sent_message, ChatMessage)
    assert sent_message.text == "Echo (from toml): Hello, world!"
    assert sent_message.destination == "+1234567890"
    assert sent_message.group_id == "group123"
