
import asyncio
import json
import time
import pytest
import logging
from unittest.mock import AsyncMock, patch, MagicMock
from pothead import (
    handle_command,
    COMMANDS,
    fire_event,
    timer_loop,
    execute_command,
    handle_incomming_message,
    process_incoming_line,
    main,
    command_filter
)
from datatypes import ChatMessage, Event, Command, Action, MessageType, EditMessage, DeleteMessage, GroupUpdateMessage
from plugin_manager import load_plugins, PLUGIN_COMMANDS


@pytest.mark.asyncio
@patch('pothead.send_signal_message', new_callable=AsyncMock)
async def test_handle_command(mock_send_signal_message):
    """
    Tests that the handle_command function correctly processes a command
    and calls send_signal_message with the echoed text.
    """
    import sys
    import plugin_manager
    # Reset plugin state to ensure a clean load
    plugin_manager.LOADED_PLUGINS.clear()
    plugin_manager.PLUGIN_COMMANDS.clear()
    plugin_manager.PLUGIN_ACTIONS.clear()
    plugin_manager.EVENT_HANDLERS.clear()
    plugin_manager.PLUGIN_SERVICES.clear()
    COMMANDS[:] = [c for c in COMMANDS if c.origin == 'sys']
    # Unload plugin modules that might have been loaded by other tests
    modules_to_unload = [m for m in sys.modules if m.startswith('plugins.')]
    for m in modules_to_unload:
        del sys.modules[m]

    # Manually load plugins to populate the command list
    load_plugins()

    from pothead import ACTIONS
    ACTIONS.extend(plugin_manager.PLUGIN_ACTIONS)
    COMMANDS.extend(plugin_manager.PLUGIN_COMMANDS)

    # Sample incoming message data
    incoming_data = {
        "params": {
            "envelope": {
                "source": "test",  # Corresponds to POTHEAD_SUPERUSER env var
                "sourceDevice": 1,
                "timestamp": time.time() * 1000,
                "dataMessage": {
                    "message": "!pot#ping",
                    "timestamp": time.time() * 1000,
                    "groupInfo": {
                        "groupId": "group123"
                    }
                }
            }
        }
    }

    # Call the handler
    await process_incoming_line(json.dumps(incoming_data))

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
async def test_handle_command_invalid_type():
    data = {"params": {"envelope": {"typingMessage": {}}}}
    assert await handle_command(data) is False

@pytest.mark.asyncio
async def test_handle_command_empty_text():
    data = {"params": {"envelope": {"source": "u", "dataMessage": {"message": "", "timestamp": 123}}}}
    assert await handle_command(data) is False

@pytest.mark.asyncio
async def test_handle_command_with_params():
    mock_handler = AsyncMock(return_value=("Resp", []))
    COMMANDS.append(Command(name="test", handler=mock_handler, help_text="h", origin="sys"))
    data = {"params": {"envelope": {"source": "test", "dataMessage": {"message": "!pot#test,p1,p2 prompt", "timestamp": time.time()*1000}}}}
    with patch("pothead.send_signal_message", new_callable=AsyncMock):
        assert await handle_command(data) is True
        mock_handler.assert_awaited_once_with("test", ["p1", "p2"], "prompt")
    COMMANDS.pop()

@pytest.mark.asyncio
async def test_fire_event():
    mock_handler = AsyncMock()
    with patch("pothead.EVENT_HANDLERS", {Event.POST_STARTUP: [mock_handler]}):
        await fire_event(Event.POST_STARTUP, "arg1", kwarg1="val1")
        mock_handler.assert_awaited_once_with("arg1", kwarg1="val1")

@pytest.mark.asyncio
async def test_fire_event_error():
    mock_handler = AsyncMock(side_effect=Exception("Handler error"))
    with patch("pothead.EVENT_HANDLERS", {Event.POST_STARTUP: [mock_handler]}):
        with patch("pothead.logger") as mock_logger:
            await fire_event(Event.POST_STARTUP)
            mock_logger.exception.assert_called()

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
    test_command = Command(name="testcmd", handler=mock_handler,
                           help_text="A test command", origin="test")

    with patch("pothead.COMMANDS", [test_command]):
        with patch("pothead.check_permission", return_value=True):
            response, _ = await execute_command("chat1", "user1", "testcmd", ["param1"], "prompt")
            assert response == "Success!"
            mock_handler.assert_awaited_once_with(
                "chat1", ["param1"], "prompt")

@pytest.mark.asyncio
async def test_execute_command_no_permission():
    with patch("pothead.check_permission", return_value=False):
        response, _ = await execute_command("chat1", "user1", "testcmd", [], None)
        assert "⛔ Permission denied" in response

@pytest.mark.asyncio
async def test_execute_command_unknown():
    with patch("pothead.check_permission", return_value=True):
        with patch("pothead.COMMANDS", []):
            response, _ = await execute_command("chat1", "user1", "unknown", [], None)
            assert "❓ Unknown command" in response


@pytest.mark.asyncio
async def test_handle_incomming_message():
    with patch("pothead.update_chat_history") as mock_update:
        with patch("pothead.fire_event", new_callable=AsyncMock) as mock_fire:
            data = {"params": {"envelope": {"source": "user1",
                                            "dataMessage": {"timestamp": time.time() * 1000, "message": "Hello"}}}}
            await handle_incomming_message(data)
            mock_update.assert_called_once()
            mock_fire.assert_awaited_once()
            call_args = mock_fire.call_args
            assert call_args[0][0] == Event.CHAT_MESSAGE_RECEIVED
            assert isinstance(call_args[0][1], ChatMessage)
            assert call_args[0][1].text == "Hello"

@pytest.mark.asyncio
async def test_handle_incomming_message_edit():
    with patch("pothead.update_chat_history") as mock_update:
        with patch("pothead.fire_event", new_callable=AsyncMock) as mock_fire:
            data = {"params": {"envelope": {"source": "user1", "editMessage": {"targetSentTimestamp": 123, "dataMessage": {"timestamp": time.time() * 1000, "message": "Edited"}}}}}
            await handle_incomming_message(data)
            mock_update.assert_called_once()
            mock_fire.assert_awaited_once()
            assert mock_fire.call_args[0][0] == Event.CHAT_MESSAGE_EDITED
            assert isinstance(mock_fire.call_args[0][1], EditMessage)

@pytest.mark.asyncio
async def test_handle_incomming_message_delete():
    with patch("pothead.update_chat_history") as mock_update:
        with patch("pothead.fire_event", new_callable=AsyncMock) as mock_fire:
            data = {"params": {"envelope": {"source": "user1", "dataMessage": {"timestamp": time.time() * 1000, "remoteDelete": {"timestamp": 123}}}}}
            await handle_incomming_message(data)
            mock_update.assert_called_once()
            mock_fire.assert_awaited_once()
            assert mock_fire.call_args[0][0] == Event.CHAT_MESSAGE_DELETED
            assert isinstance(mock_fire.call_args[0][1], DeleteMessage)

@pytest.mark.asyncio
async def test_handle_incomming_message_group_update():
    with patch("pothead.fire_event", new_callable=AsyncMock) as mock_fire:
        data = {"params": {"envelope": {"source": "user1", "dataMessage": {"timestamp": time.time() * 1000, "groupInfo": {"groupId": "g", "type": "UPDATE"}}}}}
        await handle_incomming_message(data)
        mock_fire.assert_awaited_once()
        assert mock_fire.call_args[0][0] == Event.GROUP_UPDATE
        assert isinstance(mock_fire.call_args[0][1], GroupUpdateMessage)


@pytest.mark.asyncio
async def test_handle_incomming_message_old():
    from config import settings
    with patch("pothead.update_chat_history") as mock_update:
        with patch("pothead.fire_event", new_callable=AsyncMock) as mock_fire:
            old_timestamp = (time.time() - settings.ignore_messages_older_than - 10) * 1000
            data = {"params": {"envelope": {"source": "user1",
                                            "dataMessage": {"timestamp": old_timestamp, "message": "Old"}}}}
            await handle_incomming_message(data)
            mock_update.assert_not_called()
            mock_fire.assert_not_called()

@pytest.mark.asyncio
async def test_handle_incomming_message_unknown():
    with patch("pothead.logger") as mock_logger:
        data = {"params": {"envelope": {"source": "u"}}}
        await handle_incomming_message(data)
        mock_logger.debug.assert_called()


@pytest.mark.asyncio
async def test_process_incoming_line_pending_reply():
    mock_callback = AsyncMock()
    with patch("pothead.PENDING_REPLIES", {"123": mock_callback}):
        await process_incoming_line('{"id": "123"}')
        mock_callback.assert_awaited_once()

@pytest.mark.asyncio
async def test_process_incoming_line_invalid_json():
    await process_incoming_line('invalid') # Should not raise exception


@pytest.mark.asyncio
@patch("asyncio.create_subprocess_exec")
async def test_main(mock_create_subprocess_exec):
    # Mock the subprocess to avoid actually running signal-cli
    mock_proc = AsyncMock()
    mock_proc.stdout.readline.return_value = b""  # Simulate end of output
    mock_proc.stdin = MagicMock()
    mock_proc.stdin.drain = AsyncMock()
    mock_proc.returncode = 0
    mock_create_subprocess_exec.return_value = mock_proc

    # Run main and cancel it after a short time
    async def stop_main():
        await asyncio.sleep(0.1)
        main_task.cancel()

    main_task = asyncio.create_task(main())
    await stop_main()

    # Assert that signal-cli was started
    mock_create_subprocess_exec.assert_called_once()


@pytest.mark.asyncio
@patch('pothead.send_signal_message', new_callable=AsyncMock)
async def test_handle_command_with_quote(mock_send_signal_message):
    """
    Tests that handle_command correctly processes a command with a quote,
    using the quoted text as the prompt for the command.
    """
    import sys
    import plugin_manager
    # Reset plugin state to ensure a clean load
    plugin_manager.LOADED_PLUGINS.clear()
    plugin_manager.PLUGIN_COMMANDS.clear()
    plugin_manager.PLUGIN_ACTIONS.clear()
    plugin_manager.EVENT_HANDLERS.clear()
    plugin_manager.PLUGIN_SERVICES.clear()
    COMMANDS[:] = [c for c in COMMANDS if c.origin == 'sys']

    # Unload plugin modules that might have been loaded by other tests
    modules_to_unload = [m for m in sys.modules if m.startswith('plugins.')]
    for m in modules_to_unload:
        del sys.modules[m]

    # Load plugins to get the 'echo' command
    load_plugins()

    from pothead import ACTIONS
    ACTIONS.extend(plugin_manager.PLUGIN_ACTIONS)
    COMMANDS.extend(plugin_manager.PLUGIN_COMMANDS)

    # Sample incoming message with a quote
    incoming_data = {
        "params": {
            "envelope": {
                "source": "test",
                "dataMessage": {
                    "message": "!pot#echo",
                    "timestamp": time.time() * 1000,
                    "groupInfo": {
                        "groupId": "group123"
                    },
                    "quote": {
                        "id": time.time() * 1000,
                        "author": "+123456789",
                        "text": "This is quoted text."
                    }
                }
            }
        }
    }

    # Call the handler
    await process_incoming_line(json.dumps(incoming_data))

    # Assert that send_signal_message was called
    mock_send_signal_message.assert_called_once()

    # Check that the response text is the quoted text, which the 'echo' command does
    call_args, _ = mock_send_signal_message.call_args
    sent_message = call_args[0]

    assert sent_message.text == "This is quoted text."


@pytest.mark.asyncio
async def test_process_incoming_line_calls_correct_action():
    """
    Tests that process_incoming_line correctly identifies and executes the appropriate action
    based on the incoming data.
    """
    # Define two mock actions
    mock_action_handler_1 = AsyncMock(return_value=True)
    action1 = Action(
        name="action1",
        jsonpath="$.params.envelope.dataMessage.message",
        handler=mock_action_handler_1,
        origin="test",
        filter=lambda match: match.value == "trigger1"
    )

    mock_action_handler_2 = AsyncMock(return_value=True)
    action2 = Action(
        name="action2",
        jsonpath="$.params.envelope.dataMessage.message",
        handler=mock_action_handler_2,
        origin="test",
        filter=lambda match: match.value == "trigger2"
    )

    incoming_data_for_action1 = {
        "params": {
            "envelope": {
                "source": "test",
                "dataMessage": {
                    "message": "trigger1",
                }
            }
        }
    }

    # Use patch to temporarily set the ACTIONS list for this test
    with patch('pothead.ACTIONS', [action1, action2]):
        # Process a line that should trigger action1
        await process_incoming_line(json.dumps(incoming_data_for_action1))

        # Assert that only action1's handler was called
        mock_action_handler_1.assert_awaited_once()
        mock_action_handler_2.assert_not_awaited()

def test_command_filter_invalid_path():
    match = MagicMock()
    match.path = "other"
    assert command_filter(match) is False

def test_command_filter_none_value():
    match = MagicMock()
    match.path = "message"
    match.value = None
    assert command_filter(match) is False
