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

from pydantic import BaseModel

from datatypes import ChatMessage, MessageType
from messaging import send_signal_message
from plugin_manager import get_service
from config import settings
from .config import PluginSettings, FileSender

logger: logging.Logger = logging.getLogger(__name__)


PluginSettings.settings_path = os.path.dirname(__file__)
plugin_settings = PluginSettings()


class FileSenderJob(BaseModel):
    settings: FileSender
    job_id: str


JOBS: list[FileSenderJob] = []


async def send_file_content(send_config: FileSender) -> None:
    """Reads a file, checks constraints, and sends its content."""
    file_path = send_config.file_path
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

    if len(content) > plugin_settings.max_length:
        logger.warning(
            f"File content exceeds max_length of {plugin_settings.max_length}. Truncating.")
        content = content[:plugin_settings.max_length]

    if not content:
        logger.warning(
            f"File {file_path} is empty. Nothing to send.")
        return

    logger.info(
        f"Sending file content of {file_path} to { 'group ' + send_config.group_id if send_config.group_id else 'user ' + str(send_config.destination)}")
    outgoing_message = ChatMessage(
        "filesender",
        destination=send_config.destination,
        group_id=send_config.group_id,
        text=content,
        type=MessageType.CHAT,
    )
    await send_signal_message(outgoing_message)


def initialize() -> None:
    """Initializes the plugin and schedules the file sending jobs."""
    logger.info("Initializing filesender plugin.")

    if not plugin_settings.filesender:
        logger.warning(
            "No filesender configurations found. The plugin will do nothing.")
        return

    register_cron_job: Callable[..., Any] | None = get_service(
        "register_cron_job")
    if not register_cron_job:
        logger.error(
            "Could not get 'register_cron_job' service. File sending will not be scheduled.")
        return

    for i, config in enumerate(plugin_settings.filesender):
        job_id: str = f"filesender_{i}"
        logger.info(
            f"Scheduling job {job_id} for file '{config.file_path}' with { 'interval ' + str(config.interval) if config.interval else 'time of day ' + str(config.time_of_day)}")

        if not config.destination and not config.group_id:
            logger.info(
                f"No destination or group_id specified. Messages will be send to superuser {settings.superuser}")
            config.destination = settings.superuser

        # functools.partial is not available, so we use a lambda
        # to capture the current 'config' for the cron job.
        register_cron_job(
            lambda c=config: send_file_content(c),
            interval=config.interval,
            time_of_day=config.time_of_day
        )
        JOBS.append(FileSenderJob(settings=config, job_id=job_id))

    logger.info(f"Successfully scheduled {len(JOBS)} file sending job(s).")
