
from config import settings
from messaging import send_signal_direct_message
from plugin_manager import register_event_handler
from datatypes import Event


plugin_id: str = "helloworld"


@register_event_handler(plugin_id, Event.POST_STARTUP)
async def on_startup() -> None:
    """Sends a startup message to the superuser."""
    await send_signal_direct_message(
        message="Hello from pothead!",
        recipient=settings.superuser
    )


@register_event_handler(plugin_id, Event.PRE_SHUTDOWN)
async def on_shutdown() -> None:
    """Sends a shutdown message to the superuser."""
    await send_signal_direct_message(
        message="Goodbye from pothead!",
        recipient=settings.superuser
    )
