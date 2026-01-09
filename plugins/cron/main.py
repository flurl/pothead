import logging
from typing import Callable, Awaitable
from datetime import date, datetime, time
from dataclasses import dataclass

from datatypes import Event
from plugin_manager import register_event, register_service

logger: logging.Logger = logging.getLogger(__name__)


@dataclass
class CronJob:
    func: Callable[[], Awaitable[None]]
    interval: int | None = None
    time_of_day: time | None = None
    last_run: datetime | None = None


cron_jobs: list[CronJob] = []


def register_cron_job(func: Callable[[], Awaitable[None]], interval: int | None = None, time_of_day: str | None = None) -> None:
    """
    Registers a function to be called at a specific interval or time of day.

    :param func: The async function to call.
    :param interval: The interval in minutes.
    :param time_of_day: The time of day in "HH:MM" format.
    """
    job = CronJob(
        func=func,
        interval=interval * 60 if interval else None,
        time_of_day=time.fromisoformat(time_of_day) if time_of_day else None,
    )
    cron_jobs.append(job)
    logger.info(f"Registered cron job: {func.__name__}")


async def cron_handler() -> None:
    """
    Handles the cron timer event and runs scheduled jobs.
    """
    logger.debug("Running cron jobs...")
    now: datetime = datetime.now()
    today: date = now.date()

    for job in cron_jobs:
        run_job = False
        if job.interval:
            if job.last_run is None or (now - job.last_run).total_seconds() >= job.interval:
                run_job = True
        elif job.time_of_day:
            # Check if the time of day has passed and it hasn't run today
            if now.time() >= job.time_of_day and (job.last_run is None or job.last_run.date() != today):
                run_job = True

        if run_job:
            try:
                await job.func()
                job.last_run = now
            except Exception:
                logger.exception(f"Error in cron job: {job.func.__name__}")


"""Registers the cron service."""
register_service("register_cron_job", register_cron_job)


# --- Register Event Handler ---

register_event(
    "cron",
    Event.TIMER,
    cron_handler,
)


# --- Example Usage (for demonstration) ---

# async def example_job_1():
#    logger.info("Cron job 1 running every 1 minute!")


# async def example_job_2():
#    logger.info("Cron job 2 running at a specific time!")

# register_cron_job(example_job_1, interval=1)
# register_cron_job(example_job_2, time_of_day="05:40")
