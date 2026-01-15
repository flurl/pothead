
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from datetime import datetime, time
from plugins.cron.main import register_cron_job, cron_handler, cron_jobs, CronJob

# A simple async function to be used as a mock cron job
async def mock_job():
    print("Mock job executed")

@pytest.fixture(autouse=True)
def clear_cron_jobs():
    """Fixture to clear cron_jobs before each test."""
    cron_jobs.clear()
    yield
    cron_jobs.clear()

def test_register_cron_job_interval():
    """
    Tests that a job with an interval is correctly registered.
    """
    register_cron_job(mock_job, interval=10)
    assert len(cron_jobs) == 1
    job = cron_jobs[0]
    assert job.func == mock_job
    assert job.interval == 600  # 10 minutes in seconds
    assert job.time_of_day is None

def test_register_cron_job_time_of_day_string():
    """
    Tests that a job with a time_of_day string is correctly registered.
    """
    register_cron_job(mock_job, time_of_day="14:30")
    assert len(cron_jobs) == 1
    job = cron_jobs[0]
    assert job.func == mock_job
    assert job.interval is None
    assert job.time_of_day == time(14, 30)

def test_register_cron_job_time_of_day_object():
    """
    Tests that a job with a time_of_day object is correctly registered.
    """
    t = time(9, 0)
    register_cron_job(mock_job, time_of_day=t)
    assert len(cron_jobs) == 1
    job = cron_jobs[0]
    assert job.func == mock_job
    assert job.interval is None
    assert job.time_of_day == t

@pytest.mark.asyncio
async def test_cron_handler_interval_job():
    """
    Tests that the cron_handler executes a job scheduled by interval.
    """
    mock_async_job = AsyncMock()
    register_cron_job(mock_async_job, interval=5)  # 5 minutes

    # Mock datetime to control the time "now"
    with patch('plugins.cron.main.datetime') as mock_datetime:
        # First run
        mock_datetime.now.return_value = datetime(2023, 1, 1, 12, 0, 0)
        await cron_handler()
        mock_async_job.assert_called_once()

        # Should not run again immediately
        mock_datetime.now.return_value = datetime(2023, 1, 1, 12, 4, 0) # 4 minutes later
        await cron_handler()
        mock_async_job.assert_called_once() # Still called only once

        # Should run again after interval has passed
        mock_datetime.now.return_value = datetime(2023, 1, 1, 12, 5, 1) # 5 minutes and 1 second later
        await cron_handler()
        assert mock_async_job.call_count == 2

@pytest.mark.asyncio
async def test_cron_handler_time_of_day_job():
    """
    Tests that the cron_handler executes a job scheduled for a specific time of day.
    """
    mock_async_job = AsyncMock()
    register_cron_job(mock_async_job, time_of_day="10:00")

    with patch('plugins.cron.main.datetime') as mock_datetime:
        # Before scheduled time
        mock_datetime.now.return_value = datetime(2023, 1, 1, 9, 59, 0)
        await cron_handler()
        mock_async_job.assert_not_called()

        # At scheduled time
        mock_datetime.now.return_value = datetime(2023, 1, 1, 10, 0, 0)
        await cron_handler()
        mock_async_job.assert_called_once()

        # After scheduled time, but on the same day (should not run again)
        mock_datetime.now.return_value = datetime(2023, 1, 1, 10, 1, 0)
        await cron_handler()
        mock_async_job.assert_called_once()

        # Next day, should run again
        mock_datetime.now.return_value = datetime(2023, 1, 2, 10, 0, 0)
        await cron_handler()
        assert mock_async_job.call_count == 2

@pytest.mark.asyncio
async def test_cron_handler_job_exception():
    """
    Tests that the cron_handler catches exceptions in jobs and continues.
    """
    mock_failing_job = AsyncMock(side_effect=Exception("Test Error"))
    mock_working_job = AsyncMock()

    register_cron_job(mock_failing_job, interval=1)
    register_cron_job(mock_working_job, interval=1)

    with patch('plugins.cron.main.datetime') as mock_datetime, \
         patch('plugins.cron.main.logger') as mock_logger:
        mock_datetime.now.return_value = datetime(2023, 1, 1, 12, 0, 0)
        await cron_handler()

        mock_failing_job.assert_called_once()
        mock_working_job.assert_called_once()
        mock_logger.exception.assert_called_once()
