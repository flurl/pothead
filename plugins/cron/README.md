# Cron Plugin

The Cron plugin provides a scheduling service for Pothead. Other plugins can register functions to be executed at specific intervals or at a particular time of day.

## Features

- **Interval Scheduling:** Run tasks every X minutes.
- **Time of Day Scheduling:** Run tasks at a specific time (e.g., "10:30").

## Service: `register_cron_job`

This plugin registers the `register_cron_job` service, which can be used by other plugins.

### Usage in other plugins

```python
from plugin_manager import get_service
from typing import Callable, Any

async def my_scheduled_task():
    print("My scheduled task is running!")

def initialize():
    register_cron_job = get_service("register_cron_job")
    if register_cron_job:
        # Schedule to run every 5 minutes
        register_cron_job(my_scheduled_task, interval=5)
        # Schedule to run daily at 10:30 AM
        register_cron_job(my_scheduled_task, time_of_day="10:30")
```

## How it works

The plugin listens for the `Event.TIMER` event and checks all registered jobs to see if they are due for execution.
