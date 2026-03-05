"""
Event system for the Pothead application.

Provides the event handler registry, registration decorator, and fire_event function.
"""

import logging
from collections.abc import Awaitable, Callable
from typing import Any, TypeAlias

from datatypes import Event

EventHandler: TypeAlias = Callable[[], Awaitable[None]]

EVENT_HANDLERS: dict[Event, list[Callable[[], Awaitable[None]]]] = {}

logger: logging.Logger = logging.getLogger(__name__)


def register_event_handler(
    plugin_id: str,
    event: Event,
) -> Callable[..., Any]:
    """
    Decorator to register a function as an event handler.

    Event handlers are called when specific system events occur (e.g., startup, shutdown, timer).
    Multiple handlers can be registered for the same event.

    Args:
        plugin_id: The ID of the plugin registering the handler.
        event: The `Event` enum member representing the event to listen for.

    Returns:
        The decorator function.
    """
    def decorator(func: EventHandler) -> EventHandler:
        logger.info(
            f"Registering event handler for '{event}' from '{plugin_id}'")
        if event not in EVENT_HANDLERS:
            EVENT_HANDLERS[event] = []
        EVENT_HANDLERS[event].append(func)
        return func

    return decorator


async def fire_event(event: Event, *args: Any, **kwargs: Any) -> None:
    """Fires an event and runs all registered handlers."""
    logger.info(f"Firing event: {event}")
    if event in EVENT_HANDLERS:
        for handler in EVENT_HANDLERS[event]:
            try:
                await handler(*args, **kwargs)
            except Exception:
                logger.exception(f"Error in event handler for {event}")
