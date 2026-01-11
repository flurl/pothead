"""
This plugin allows scheduling the sending of file contents as messages.
It reads configurations from `config.toml` within its own directory.
Each configuration specifies a file path, a destination (user or group),
and a schedule (interval or specific time of day).

The plugin uses the `cron` service to schedule these tasks.
"""

import logging
import os
from typing import Callable, Any
import mimetypes

from datatypes import ChatMessage
from messaging import send_signal_message
from plugin_manager import get_service
from config import settings

logger: logging.Logger = logging.getLogger(__name__)

plugin_settings: dict[str, Any] = settings.plugins.get("filesender", {})
max_length: int = plugin_settings.get("max_length", 1000)
filesender_configs: list[dict[str, Any]
                         ] = plugin_settings.get("filesender", [])

JOBS: list[dict[str, Any]] = []


async def send_file_content(send_config: dict[str, Any]) -> None:
    """Reads a file, checks constraints, and sends its content."""
    file_path = send_config.get("file_path")
    if not file_path:
        logger.error("File sender config missing 'file_path'")
        return

    if not os.path.isabs(file_path):
        file_path = os.path.join(os.path.dirname(__file__), file_path)

    logger.info(f"Executing send_file_content for {file_path}")

    if not os.path.exists(file_path):
        logger.error(f"File not found: {file_path}")
        return

    # Check if it's a text file
    mime_type, _ = mimetypes.guess_type(file_path)
    if not mime_type or not mime_type.startswith('text/'):
        logger.error(
            f"File is not a text file: {file_path} (MIME type: {mime_type})")
        return

    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content: str = f.read()
    except Exception as e:
        logger.error(f"Could not read file {file_path}: {e}")
        return

    if len(content) > max_length:
        logger.warning(
            f"File content exceeds max_length of {max_length}. Truncating.")
        content = content[:max_length]

    if not content:
        logger.warning(
            f"File {file_path} is empty. Nothing to send.")
        return

    destination = send_config.get("destination")
    group_id = send_config.get("group_id")

    logger.info(
        f"Sending file content of {file_path} to { 'group ' + group_id if group_id else 'user ' + str(destination)}")
    outgoing_message = ChatMessage(
        "filesender",
        destination=destination,
        group_id=group_id,
        text=content,
    )
    await send_signal_message(outgoing_message)


def initialize() -> None:
    """Initializes the plugin and schedules the file sending jobs."""
    logger.info("Initializing filesender plugin.")

    if not filesender_configs:
        logger.warning(
            "No filesender configurations found. The plugin will do nothing.")
        return

    register_cron_job: Callable[..., Any] | None = get_service(
        "register_cron_job")
    if not register_cron_job:
        logger.error(
            "Could not get 'register_cron_job' service. File sending will not be scheduled.")
        return

    for i, config in enumerate(filesender_configs):
        job_id: str = f"filesender_{i}"
        logger.info(
            f"Scheduling job {job_id} for file '{config.get('file_path')}' with { 'interval ' + str(config.get('interval')) if config.get('interval') else 'time of day ' + str(config.get('time_of_day'))}")

        if not config.get("destination") and not config.get("group_id"):
            logger.info(
                f"No destination or group_id specified. Messages will be send to superuser {settings.superuser}")
            config["destination"] = settings.superuser

        # functools.partial is not available, so we use a lambda
        # to capture the current 'config' for the cron job.
        register_cron_job(
            lambda c=config: send_file_content(c),  # type: ignore
            interval=config.get("interval"),
            time_of_day=config.get("time_of_day")
        )
        JOBS.append({"settings": config, "job_id": job_id})

    logger.info(f"Successfully scheduled {len(JOBS)} file sending job(s).")
