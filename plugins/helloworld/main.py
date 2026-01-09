
from config import settings
from messaging import send_signal_direct_message
from plugin_manager import register_event
from datatypes import Event


plugin_id: str = "helloworld"


async def on_startup() -> None:
    """Sends a startup message to the superuser."""
    await send_signal_direct_message(
        message="Hello from pothead!",
        recipient=settings.superuser
    )


async def on_shutdown() -> None:
    """Sends a shutdown message to the superuser."""
    await send_signal_direct_message(
        message="Goodbye from pothead!",
        recipient=settings.superuser
    )

register_event(plugin_id, Event.POST_STARTUP, on_startup)
register_event(plugin_id, Event.PRE_SHUTDOWN, on_shutdown)
