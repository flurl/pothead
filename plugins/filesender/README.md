# FileSender Plugin

The FileSender plugin allows you to schedule the sending of text file contents as Signal messages.

## Features

- **Scheduled File Sending:** Send the content of local text files to specific users or groups on a schedule.
- **Support for Cron:** Integrates with the `cron` plugin for scheduling.

## Configuration

Configurations are defined in `plugins/filesender/config.toml`. Each entry in the `filesender` list can have:

- `file_path`: Path to the text file (relative to the plugin directory or absolute).
- `destination`: Phone number of the recipient (for direct messages).
- `group_id`: ID of the recipient group.
- `interval`: Interval in minutes.
- `time_of_day`: Time of day in "HH:MM" format.

Example `config.toml`:

```toml
max_length = 2000

[[filesender]]
file_path = "example_file.txt"
destination = "+123456789"
interval = 60

[[filesender]]
file_path = "daily_report.txt"
group_id = "group_id_here"
time_of_day = "08:00"
```

## Constraints

- Only files with a `text/` MIME type are supported.
- Message length is limited by the `max_length` setting (default: 2000 characters).
