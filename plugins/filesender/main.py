"""
This plugin allows scheduling the sending of file contents as messages.
It reads configurations from `config.toml` within its own directory.
Each configuration specifies a file path, a destination (user or group),
and a schedule (interval or specific time of day).

The plugin uses the `cron` service to schedule these tasks.
"""

import glob
import logging
import os
from typing import Callable, Any
import mimetypes

from pydantic import BaseModel

from datatypes import ChatMessage, MessageType
from messaging import send_signal_message
from plugin_manager import get_service, register_command
from config import settings
from utils import get_safe_chat_dir
from .config import PluginSettings, FileSender

logger: logging.Logger = logging.getLogger(__name__)


PluginSettings.settings_path = os.path.dirname(__file__)
plugin_settings = PluginSettings()

plugin_id: str = "filesender"


class FileSenderJob(BaseModel):
    settings: FileSender
    job_id: str


JOBS: list[FileSenderJob] = []


def _resolve_outbox_base() -> str:
    outbox_dir: str = plugin_settings.outbox_dir
    if not os.path.isabs(outbox_dir):
        outbox_dir = os.path.join(os.path.dirname(__file__), outbox_dir)
    return outbox_dir


async def scan_outbox() -> None:
    """Scans the outbox directory and sends pending message files."""
    outbox_base: str = _resolve_outbox_base()
    if not os.path.isdir(outbox_base):
        return

    for entry in os.scandir(outbox_base):
        if not entry.is_dir():
            continue

        chat_id_file: str = os.path.join(entry.path, "chat_id.txt")
        if not os.path.exists(chat_id_file):
            continue

        try:
            with open(chat_id_file, "r", encoding="utf-8") as f:
                chat_id: str = f.read().strip()
        except Exception as e:
            logger.error(f"Could not read chat_id.txt in {entry.path}: {e}")
            continue

        if not chat_id:
            continue

        md_files: list[str] = sorted(
            glob.glob(os.path.join(entry.path, "*.md")))
        for file_path in md_files:
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    content = f.read()
            except Exception as e:
                logger.error(f"Could not read outbox file {file_path}: {e}")
                continue

            if not content:
                logger.warning(f"Outbox file {file_path} is empty, skipping.")
                continue

            if len(content) > plugin_settings.max_length:
                logger.warning(
                    f"Outbox file {file_path} exceeds max_length of {plugin_settings.max_length}. Truncating.")
                content: str = content[:plugin_settings.max_length]

            destination: str | None = chat_id if chat_id.startswith(
                "+") else None
            group_id: None | str = None if chat_id.startswith("+") else chat_id

            # TODO: make use of abstraction in messaging.py?
            outgoing_message = ChatMessage(
                source=plugin_id,
                source_name=plugin_id,
                destination=destination,
                group_id=group_id,
                text=content,
                type=MessageType.CHAT,
            )

            try:
                await send_signal_message(outgoing_message)
                os.remove(file_path)
                logger.info(f"Sent and deleted outbox file {file_path}")
            except Exception as e:
                logger.error(f"Failed to send outbox file {file_path}: {e}")


@register_command(plugin_id, "outboxdir", "Show (and create) outbox dir for this chat")
async def cmd_outboxdir(chat_id: str, params: list[str], prompt: str | None) -> tuple[str, list[str]]:
    """Returns the outbox directory path for the current chat, creating it if needed."""
    outbox_base: str = _resolve_outbox_base()
    chat_dir: str = get_safe_chat_dir(outbox_base, chat_id)
    os.makedirs(chat_dir, exist_ok=True)

    chat_id_file: str = os.path.join(chat_dir, "chat_id.txt")
    with open(chat_id_file, "w", encoding="utf-8") as f:
        f.write(chat_id)

    return chat_dir, []


async def send_file_content(send_config: FileSender) -> None:
    """Reads a file, checks constraints, and sends its content."""
    file_path: str = send_config.file_path
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
        source="filesender",
        source_name="filesender",
        destination=send_config.destination,
        group_id=send_config.group_id,
        text=content,
        type=MessageType.CHAT,
    )
    await send_signal_message(outgoing_message)


def initialize() -> None:
    """Initializes the plugin and schedules the file sending jobs."""
    logger.info("Initializing filesender plugin.")

    register_cron_job: Callable[..., Any] | None = get_service(
        "register_cron_job")
    if not register_cron_job:
        logger.error(
            "Could not get 'register_cron_job' service. File sending will not be scheduled.")
        return

    register_cron_job(scan_outbox, interval=plugin_settings.outbox_interval)
    logger.info(
        f"Scheduled outbox scanner every {plugin_settings.outbox_interval} minute(s).")

    if not plugin_settings.filesender:
        logger.warning(
            "No filesender configurations found. Scheduled file sending will not run.")
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
