from datetime import time
from typing import Any, cast

from pydantic import BaseModel, field_validator, model_validator
from plugin_manager import PluginSettingsBase


class FileSender(BaseModel):
    destination: str | None = None
    group_id: str | None = None
    time_of_day: time | None = None
    interval: int | None = None
    file_path: str

    @field_validator('time_of_day', mode='before')
    @classmethod
    def parse_time(cls, v: str | time | None) -> time | None:
        """Parse time string to time object."""
        if v is None or isinstance(v, time):
            return v
        # Parse time in HH:MM format
        parts: list[str] = v.split(':')
        if len(parts) == 2:
            return time(hour=int(parts[0]), minute=int(parts[1]))
        raise ValueError(f"Invalid time format: {v}")

    @model_validator(mode='before')
    @classmethod
    def check_either_or_fields(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data

        # Cast to dict[str, Any] to avoid "partially unknown" warning
        data = cast(dict[str, Any], data)

        if not ('time_of_day' in data or 'interval' in data):
            raise ValueError(
                'Either "time_of_day" or "interval" must be provided.')
        return data


class PluginSettings(PluginSettingsBase):
    """Main configuration for the File Sender plugin."""

    max_length: int = 1000
    filesender: list[FileSender] = []
