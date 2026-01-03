
import tomllib
from importlib.machinery import ModuleSpec
import importlib.util
import logging
import os
from collections.abc import Awaitable, Callable
from types import ModuleType
from typing import Any

from datatypes import Action
from config import settings


logger: logging.Logger = logging.getLogger(__name__)

PENDING_REPLIES: dict[str, Callable[[dict[str, Any]], Awaitable[None]]] = {}
LOADED_PLUGINS: dict[str, dict[str, Any]] = {}

PLUGIN_ACTIONS: list[Action] = []


def register_action(name: str, jsonpath: str, handler: Callable[[dict[str, Any]], Awaitable[None]]) -> None:
    """Decorator to register a plugin action."""
    logger.info(f"Registering plugin action: {name}")
    action = Action(name=name, jsonpath=jsonpath, handler=handler)
    PLUGIN_ACTIONS.append(action)


def load_plugins() -> None:
    """Loads plugins from the 'plugins' directory by reading a manifest.toml file."""
    plugins_dir = "plugins"
    if not os.path.isdir(plugins_dir):
        logger.warning(f"Plugin directory '{plugins_dir}' not found.")
        return

    for plugin_name in os.listdir(plugins_dir):
        plugin_dir: str = os.path.join(plugins_dir, plugin_name)
        if not os.path.isdir(plugin_dir):
            continue

        # 1. Read and validate manifest
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

        # only load if enabled in settings
        if plugin_id not in settings.plugins:
            continue

        if plugin_id in LOADED_PLUGINS:
            logger.error(
                f"Duplicate plugin ID '{plugin_id}'. Skipping {plugin_name}.")
            continue

        # 2. Load the plugin module
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
            logger.info(
                f"Successfully loaded plugin: {manifest.get('name', plugin_id)} "
                f"v{manifest.get('version', 'N/A')}"
            )
        except Exception as e:
            logger.error(
                f"Failed to load plugin module for {plugin_name}: {e}", exc_info=True)
