
import tomllib
from importlib.machinery import ModuleSpec
import importlib.util
import logging
import os
from collections.abc import Awaitable, Callable
from types import ModuleType
from typing import Any

from datatypes import Action, Priority, Command, Event
from config import settings


logger: logging.Logger = logging.getLogger(__name__)

PENDING_REPLIES: dict[str, Callable[[dict[str, Any]], Awaitable[None]]] = {}
LOADED_PLUGINS: dict[str, dict[str, Any]] = {}

PLUGIN_ACTIONS: list[Action] = []
PLUGIN_COMMANDS: list[Command] = []
EVENT_HANDLERS: dict[Event, list[Callable[[], Awaitable[None]]]] = {}
PLUGIN_SERVICES: dict[str, Callable[..., Any]] = {}


def register_service(service_name: str, service_function: Callable[..., Any]) -> None:
    """Registers a function from a plugin to be used by other plugins."""
    if service_name in PLUGIN_SERVICES:
        logger.warning(f"Service '{service_name}' is being overwritten.")
    logger.info(f"Registering service: {service_name}")
    PLUGIN_SERVICES[service_name] = service_function


def get_service(service_name: str) -> Callable[..., Any] | None:
    """Gets a service function registered by a plugin."""
    service: Callable[..., Any] | None = PLUGIN_SERVICES.get(service_name)
    if not service:
        logger.warning(f"Service '{service_name}' not found.")
    return service


def register_event(
    plugin_id: str,
    event: Event,
    handler: Callable[[], Awaitable[None]],
) -> None:
    """Decorator to register a plugin event handler."""
    logger.info(f"Registering event handler for '{event}' from '{plugin_id}'")
    if event not in EVENT_HANDLERS:
        EVENT_HANDLERS[event] = []
    EVENT_HANDLERS[event].append(handler)


def register_action(
    plugin_id: str,
    name: str,
    jsonpath: str,
    handler: Callable[[dict[str, Any]], Awaitable[bool]],
    priority: Priority = Priority.NORMAL,
    filter: Callable[[Any], bool] | None = None,
) -> None:
    """Decorator to register a plugin action."""
    logger.info(f"Registering plugin action '{name}' from '{plugin_id}'")
    action = Action(name=name, jsonpath=jsonpath, handler=handler,
                    priority=priority, filter=filter, origin=f"plugin:{plugin_id}")
    PLUGIN_ACTIONS.append(action)


def register_command(
    plugin_id: str,
    name: str,
    handler: Callable[[str, list[str], str | None], Awaitable[tuple[str, list[str]]]],
    help_text: str,
) -> None:
    """Decorator to register a plugin command."""
    logger.info(f"Registering plugin command '{name}' from '{plugin_id}'")
    command = Command(name=name, handler=handler,
                      help_text=help_text, origin=f"plugin:{plugin_id}")
    PLUGIN_COMMANDS.append(command)


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
