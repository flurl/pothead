
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, mock_open
import os
from plugins.filesender.main import initialize, send_file_content
from plugins.filesender.config import FileSender, PluginSettings
from datatypes import ChatMessage

# Sample config to be used in tests
sample_config = [
    FileSender(
        file_path="test.txt",
        destination="+12345",
        group_id=None,
        interval=10,
        time_of_day=None
    ),
    FileSender(
        file_path="/abs/path/another.txt",
        destination=None,
        group_id="group123",
        interval=None,
        time_of_day="08:00"
    )
]

@pytest.fixture
def mock_plugin_settings():
    """Fixture to mock the plugin settings."""
    with patch('plugins.filesender.main.plugin_settings') as mock_settings:
        mock_settings.filesender = sample_config
        mock_settings.max_length = 100
        yield mock_settings

def test_initialize(mock_plugin_settings):
    """
    Tests the initialize function to ensure it schedules cron jobs correctly.
    """
    from datetime import time
    mock_register_cron_job = MagicMock()
    with patch('plugins.filesender.main.get_service', return_value=mock_register_cron_job) as mock_get_service:
        initialize()

        mock_get_service.assert_called_once_with("register_cron_job")
        assert mock_register_cron_job.call_count == 2

        # Check the first call
        args1, kwargs1 = mock_register_cron_job.call_args_list[0]
        assert 'interval' in kwargs1 and kwargs1['interval'] == 10
        assert 'time_of_day' in kwargs1 and kwargs1['time_of_day'] is None

        # Check the second call
        args2, kwargs2 = mock_register_cron_job.call_args_list[1]
        assert 'interval' in kwargs2 and kwargs2['interval'] is None
        assert 'time_of_day' in kwargs2 and kwargs2['time_of_day'] == time(8, 0)

@pytest.mark.asyncio
@patch('plugins.filesender.main.send_signal_message', new_callable=AsyncMock)
@patch('os.path.exists', return_value=True)
@patch('mimetypes.guess_type', return_value=('text/plain', None))
async def test_send_file_content_success(mock_guess_type, mock_exists, mock_send_signal_message, mock_plugin_settings):
    """
    Tests successful sending of file content.
    """
    file_content = "Hello, this is a test."
    send_config = sample_config[0]

    with patch('builtins.open', mock_open(read_data=file_content)) as mocked_open:
        await send_file_content(send_config)

        mocked_open.assert_called_once()
        mock_send_signal_message.assert_called_once()
        sent_message = mock_send_signal_message.call_args[0][0]
        assert isinstance(sent_message, ChatMessage)
        assert sent_message.text == file_content
        assert sent_message.destination == send_config.destination

@pytest.mark.asyncio
@patch('plugins.filesender.main.send_signal_message', new_callable=AsyncMock)
@patch('os.path.exists', return_value=False)
async def test_send_file_content_file_not_found(mock_exists, mock_send_signal_message, mock_plugin_settings):
    """
    Tests that nothing is sent if the file does not exist.
    """
    await send_file_content(sample_config[0])
    mock_send_signal_message.assert_not_called()

@pytest.mark.asyncio
@patch('plugins.filesender.main.send_signal_message', new_callable=AsyncMock)
@patch('os.path.exists', return_value=True)
@patch('mimetypes.guess_type', return_value=('application/octet-stream', None))
async def test_send_file_content_not_text_file(mock_guess_type, mock_exists, mock_send_signal_message, mock_plugin_settings):
    """
    Tests that nothing is sent if the file is not a text file.
    """
    with patch('builtins.open', mock_open(read_data="binary data")):
        await send_file_content(sample_config[0])
        mock_send_signal_message.assert_not_called()

@pytest.mark.asyncio
@patch('plugins.filesender.main.send_signal_message', new_callable=AsyncMock)
@patch('os.path.exists', return_value=True)
@patch('mimetypes.guess_type', return_value=('text/plain', None))
async def test_send_file_content_truncation(mock_guess_type, mock_exists, mock_send_signal_message, mock_plugin_settings):
    """
    Tests that file content is truncated if it exceeds max_length.
    """
    long_content = "a" * 150
    mock_plugin_settings.max_length = 100

    with patch('builtins.open', mock_open(read_data=long_content)):
        await send_file_content(sample_config[0])

        mock_send_signal_message.assert_called_once()
        sent_message = mock_send_signal_message.call_args[0][0]
        assert len(sent_message.text) == 100
        assert sent_message.text == "a" * 100

@pytest.mark.asyncio
@patch('plugins.filesender.main.send_signal_message', new_callable=AsyncMock)
@patch('os.path.exists', return_value=True)
@patch('mimetypes.guess_type', return_value=('text/plain', None))
async def test_send_file_content_empty_file(mock_guess_type, mock_exists, mock_send_signal_message, mock_plugin_settings):
    """
    Tests that nothing is sent if the file is empty.
    """
    with patch('builtins.open', mock_open(read_data="")):
        await send_file_content(sample_config[0])
        mock_send_signal_message.assert_not_called()
