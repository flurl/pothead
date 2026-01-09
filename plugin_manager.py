"""
The `plugin_manager` module is responsible for dynamically loading, initializing,
and managing plugins for the Pothead application. It provides decorators and
functions for plugins to register their functionalities, such as actions,
commands, event handlers, and services.

Plugins are discovered in the 'plugins' directory, and each plugin is expected
to have a `manifest.toml` file describing its metadata and a `main.py` file
containing its core logic.

Key functionalities provided by this module:
- **Plugin Loading:** Scans the 'plugins' directory, reads `manifest.toml` files,
  and imports `main.py` modules for enabled plugins.
- **Action Registration:** Allows plugins to register functions that act on
  incoming Signal messages based on JSONPath expressions and optional filters.
- **Command Registration:** Enables plugins to define custom commands that users
  can invoke through chat messages.
- **Event Handler Registration:** Provides a mechanism for plugins to subscribe
  to system-wide events (e.g., `POST_STARTUP`, `PRE_SHUTDOWN`, `TIMER`).
- **Service Registration and Discovery:** Facilitates inter-plugin communication
  by allowing plugins to expose and consume shared functionalities (services).
"""

import tomllib
from importlib.machinery import ModuleSpec
import importlib.util
import logging
import os
from collections.abc import Awaitable, Callable
from types import ModuleType
from typing import Any, TypeAlias

from datatypes import Action, Priority, Command, Event
from config import settings

EventHandler: TypeAlias = Callable[[], Awaitable[None]]
ActionHandler: TypeAlias = Callable[[dict[str, Any]], Awaitable[bool]]
CommandHandler: TypeAlias = Callable[[
    str, list[str], str | None], Awaitable[tuple[str, list[str]]]]


logger: logging.Logger = logging.getLogger(__name__)

PENDING_REPLIES: dict[str, Callable[[dict[str, Any]], Awaitable[None]]] = {}
LOADED_PLUGINS: dict[str, dict[str, Any]] = {}

PLUGIN_ACTIONS: list[Action] = []
PLUGIN_COMMANDS: list[Command] = []
EVENT_HANDLERS: dict[Event, list[Callable[[], Awaitable[None]]]] = {}
PLUGIN_SERVICES: dict[str, Callable[..., Any]] = {}


def register_service(service_name: str) -> Callable[..., Any]:
    """
    Decorator to register a function as a service available to other plugins.

    Services are stored in a global registry and can be retrieved using `get_service`.
    This allows plugins to expose functionality to other plugins without direct imports.

    Args:
        service_name: The unique name of the service. If a service with this name
                      already exists, a warning is logged and it is overwritten.

    Returns:
        The decorator function.
    """
    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        if service_name in PLUGIN_SERVICES:
            logger.warning(f"Service '{service_name}' is being overwritten.")
        logger.info(f"Registering service: {service_name}")
        PLUGIN_SERVICES[service_name] = func
        return func

    return decorator


def get_service(service_name: str) -> Callable[..., Any] | None:
    """Gets a service function registered by a plugin."""
    service: Callable[..., Any] | None = PLUGIN_SERVICES.get(service_name)
    if not service:
        logger.warning(f"Service '{service_name}' not found.")
    return service


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


def register_action(
    plugin_id: str,
    name: str,
    jsonpath: str,
    priority: Priority = Priority.NORMAL,
    filter: Callable[[Any], bool] | None = None
) -> Callable[..., Any]:
    """
    Decorator to register a function as an action handler for incoming messages.

    Actions are evaluated against incoming JSON messages from signal-cli. If the
    `jsonpath` matches and the optional `filter` returns True, the decorated function
    is executed.

    Args:
        plugin_id: The ID of the plugin registering the action.
        name: A descriptive name for the action (used in logging).
        jsonpath: A JSONPath string to locate data within the message envelope.
                  If the path exists, the action is considered a match (unless filtered).
        priority: The execution priority. Higher priority actions run first.
                  Defaults to `Priority.NORMAL`.
        filter: An optional callable that takes the value found at `jsonpath` and
                returns `True` if the action should run, or `False` otherwise.

    Returns:
        The decorator function.
    """
    def decorator(func: ActionHandler) -> ActionHandler:
        logger.info(f"Registering plugin action '{name}' from '{plugin_id}'")
        action = Action(name=name, jsonpath=jsonpath, handler=func,
                        priority=priority, filter=filter, origin=f"plugin:{plugin_id}")
        PLUGIN_ACTIONS.append(action)
        return func

    return decorator


def register_command(
    plugin_id: str,
    name: str,
    help_text: str,
) -> Callable[..., Any]:
    """
    Decorator to register a function as a command handler.

    Commands are triggered by messages starting with specific prefixes (e.g., "!TRIGGER#").
    The decorated function is called when the command name matches.

    Args:
        plugin_id: The ID of the plugin registering the command.
        name: The name of the command (e.g., "ping" for "!ping").
        help_text: A description of what the command does, shown in help listings.

    Returns:
        The decorator function.
    """
    def decorator(func: CommandHandler) -> CommandHandler:
        logger.info(f"Registering plugin command '{name}' from '{plugin_id}'")
        command = Command(name=name, handler=func,
                          help_text=help_text, origin=f"plugin:{plugin_id}")
        PLUGIN_COMMANDS.append(command)
        return func

    return decorator


def load_plugins() -> None:
    """Loads plugins from the 'plugins' directory by reading a manifest.toml file."""
    plugins_dir = "plugins"
    loaded_modules: dict[str, ModuleType] = {}

    if not os.path.isdir(plugins_dir):
        logger.warning(f"Plugin directory '{plugins_dir}' not found.")
        return

    # Phase 1: Load plugin modules
    for plugin_name in os.listdir(plugins_dir):
        plugin_dir: str = os.path.join(plugins_dir, plugin_name)
        if not os.path.isdir(plugin_dir):
            continue

        manifest_path: str = os.path.join(plugin_dir, "manifest.toml")
        if not os.path.isfile(manifest_path):
            logger.debug(f"No manifest.toml in {plugin_dir}, skipping.")
            continue

        try:
            with open(manifest_path, "rb") as f:
                manifest: dict[str, Any] = tomllib.load(f)
        except Exception as e:
            logger.error(f"Error loading manifest for {plugin_name}: {e}")
            continue

        plugin_id: str | None = manifest.get("id")
        if not plugin_id:
            logger.warning(
                f"Plugin {plugin_name} MANIFEST has no 'id'. Skipping.")
            continue

        if plugin_id not in settings.plugins:
            continue

        if plugin_id in LOADED_PLUGINS:
            logger.error(
                f"Duplicate plugin ID '{plugin_id}'. Skipping {plugin_name}.")
            continue

        main_file_path: str = os.path.join(plugin_dir, "main.py")
        if not os.path.isfile(main_file_path):
            logger.error(
                f"Found manifest for '{plugin_id}' but no main.py. Skipping.")
            continue

        try:
            module_name: str = f"plugins.{plugin_id}.main"
            spec: ModuleSpec | None = importlib.util.spec_from_file_location(
                module_name, main_file_path)
            if not (spec and spec.loader):
                logger.error(f"Could not create module spec for {plugin_name}")
                continue

            module: ModuleType = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            LOADED_PLUGINS[plugin_id] = manifest
            loaded_modules[plugin_id] = module
            logger.info(
                f"Loaded module for plugin: {manifest.get('name', plugin_id)} "
                f"v{manifest.get('version', 'N/A')}"
            )
        except Exception as e:
            logger.error(
                f"Failed to load plugin module for {plugin_name}: {e}", exc_info=True)

    # Phase 2: Initialize plugins
    for plugin_id, module in loaded_modules.items():
        if hasattr(module, "initialize"):
            logger.info(f"Initializing plugin: {plugin_id}")
            try:
                module.initialize()
            except Exception as e:
                logger.error(
                    f"Failed to initialize plugin {plugin_id}: {e}", exc_info=True)
