
import asyncio
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from pothead import (
    handle_command,
    COMMANDS,
    fire_event,
    timer_loop,
    execute_command,
    handle_history,
    process_incoming_line,
    main,
)
from datatypes import ChatMessage, Event, Command
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

@pytest.mark.asyncio
async def test_fire_event():
    mock_handler = AsyncMock()
    with patch("pothead.EVENT_HANDLERS", {Event.POST_STARTUP: [mock_handler]}):
        await fire_event(Event.POST_STARTUP)
        mock_handler.assert_awaited_once()

@pytest.mark.asyncio
async def test_timer_loop():
    side_effects = [None, asyncio.CancelledError]
    with patch("asyncio.sleep", new_callable=AsyncMock, side_effect=side_effects) as mock_sleep:
        with patch("pothead.fire_event", new_callable=AsyncMock) as mock_fire_event:
            with pytest.raises(asyncio.CancelledError):
                await timer_loop()
            mock_fire_event.assert_awaited_once_with(Event.TIMER)
            assert mock_sleep.call_count == 2

@pytest.mark.asyncio
async def test_execute_command():
    mock_handler = AsyncMock(return_value=("Success!", []))
    test_command = Command(name="testcmd", handler=mock_handler, help_text="A test command", origin="test")

    with patch("pothead.COMMANDS", [test_command]):
        with patch("pothead.check_permission", return_value=True):
            response, _ = await execute_command("chat1", "user1", "testcmd", ["param1"], "prompt")
            assert response == "Success!"
            mock_handler.assert_awaited_once_with("chat1", ["param1"], "prompt")

@pytest.mark.asyncio
async def test_handle_history():
    with patch("pothead.update_chat_history") as mock_update:
        data = {"params": {"envelope": {"source": "user1", "dataMessage": {"message": "Hello"}}}}
        await handle_history(data)
        mock_update.assert_called_once()

@pytest.mark.asyncio
async def test_process_incoming_line_pending_reply():
    mock_callback = AsyncMock()
    with patch("pothead.PENDING_REPLIES", {"123": mock_callback}):
        await process_incoming_line('{"id": "123"}')
        mock_callback.assert_awaited_once()

@pytest.mark.asyncio
@patch("asyncio.create_subprocess_exec")
async def test_main(mock_create_subprocess_exec):
    # Mock the subprocess to avoid actually running signal-cli
    mock_proc = AsyncMock()
    mock_proc.stdout.readline.return_value = b""  # Simulate end of output
    mock_proc.stdin = MagicMock()
    mock_proc.stdin.drain = AsyncMock()
    mock_create_subprocess_exec.return_value = mock_proc

    # Run main and cancel it after a short time
    async def stop_main():
        await asyncio.sleep(0.1)
        main_task.cancel()

    main_task = asyncio.create_task(main())
    await stop_main()

    # Assert that signal-cli was started
    mock_create_subprocess_exec.assert_called_once()
