
import pytest
from unittest.mock import AsyncMock, patch
from events import fire_event, register_event_handler, EVENT_HANDLERS
from datatypes import Event


@pytest.mark.asyncio
async def test_fire_event():
    mock_handler = AsyncMock()
    with patch("events.EVENT_HANDLERS", {Event.POST_STARTUP: [mock_handler]}):
        await fire_event(Event.POST_STARTUP, "arg1", kwarg1="val1")
        mock_handler.assert_awaited_once_with("arg1", kwarg1="val1")


@pytest.mark.asyncio
async def test_fire_event_error():
    mock_handler = AsyncMock(side_effect=Exception("Handler error"))
    with patch("events.EVENT_HANDLERS", {Event.POST_STARTUP: [mock_handler]}):
        with patch("events.logger") as mock_logger:
            await fire_event(Event.POST_STARTUP)
            mock_logger.exception.assert_called()


@pytest.mark.asyncio
async def test_fire_event_no_handlers():
    with patch("events.EVENT_HANDLERS", {}):
        # Should not raise any exception
        await fire_event(Event.POST_STARTUP)


def test_register_event_handler():
    with patch("events.EVENT_HANDLERS", {}) as mock_handlers:
        @register_event_handler("test_plugin", Event.TIMER)
        async def my_handler() -> None:
            pass

        assert Event.TIMER in mock_handlers
        assert my_handler in mock_handlers[Event.TIMER]


def test_register_event_handler_multiple():
    with patch("events.EVENT_HANDLERS", {}) as mock_handlers:
        @register_event_handler("test_plugin", Event.POST_STARTUP)
        async def handler_one() -> None:
            pass

        @register_event_handler("test_plugin", Event.POST_STARTUP)
        async def handler_two() -> None:
            pass

        assert len(mock_handlers[Event.POST_STARTUP]) == 2
        assert handler_one in mock_handlers[Event.POST_STARTUP]
        assert handler_two in mock_handlers[Event.POST_STARTUP]
