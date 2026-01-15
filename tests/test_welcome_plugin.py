
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, mock_open
import os

from plugins.welcome.main import (
    action_group_update,
    group_info_handler,
    cmd_initgroup,
    extract_members,
    find_new_members,
    save_members,
    get_group_dir,
    Member
)

# --- Test Data ---

GROUP_UPDATE_DATA = {
    "params": {
        "envelope": {
            "source": "+12345",
            "syncMessage": {
                "sentMessage": {
                    "message": "Some group update message",
                    "groupInfo": {
                        "groupId": "group123",
                        "type": "UPDATE"
                    }
                }
            }
        }
    }
}

GROUP_INFO_DATA = {
    "result": [
        {
            "id": "group123",
            "members": [
                {"number": "+111", "uuid": "uuid1"},
                {"number": "+222", "uuid": "uuid2"},
            ]
        }
    ]
}

# --- Fixtures ---

@pytest.fixture
def mock_messaging_welcome():
    """Fixture to mock messaging functions for the welcome plugin."""
    with patch('plugins.welcome.main.get_group_info', new_callable=AsyncMock) as mock_get_info, \
         patch('plugins.welcome.main.send_signal_group_message', new_callable=AsyncMock) as mock_send_msg:
        yield {
            "get_group_info": mock_get_info,
            "send_signal_group_message": mock_send_msg
        }

@pytest.fixture
def mock_file_system():
    """Fixture to mock file system operations."""
    with patch('os.path.exists') as mock_exists, \
         patch('builtins.open', new_callable=mock_open) as mock_open_file, \
         patch('os.makedirs') as mock_makedirs:
        # It's useful to have exists return a default value
        mock_exists.return_value = False
        yield {
            "exists": mock_exists,
            "open": mock_open_file,
            "makedirs": mock_makedirs
        }


# --- Tests for action_group_update ---

@pytest.mark.asyncio
async def test_action_group_update(mock_messaging_welcome):
    await action_group_update(GROUP_UPDATE_DATA)
    mock_messaging_welcome["get_group_info"].assert_called_once()
    # Check that the callback is passed
    assert callable(mock_messaging_welcome["get_group_info"].call_args[0][1])


# --- Tests for group_info_handler ---

@pytest.mark.asyncio
async def test_group_info_handler_new_member(mock_messaging_welcome, mock_file_system):
    chat_id = "group123"
    # No existing members file
    mock_file_system["exists"].return_value = False

    # Mock reading welcome message
    welcome_message = "Welcome!"
    mock_file_system["exists"].side_effect = [False, True] # First for members.csv, second for welcome_message.txt
    mock_file_system["open"].return_value.read.return_value = welcome_message

    with patch('plugins.welcome.main.save_members') as mock_save_members:
        await group_info_handler(GROUP_INFO_DATA)

        # It should detect new members and send a message
        mock_messaging_welcome["send_signal_group_message"].assert_called_once_with(welcome_message, chat_id)
        # It should save the new list of members
        mock_save_members.assert_called_once()


@pytest.mark.asyncio
async def test_group_info_handler_no_new_member(mock_messaging_welcome, mock_file_system):
    chat_id = "group123"
    # Existing members file contains all current members
    existing_members_csv = "+111,uuid1,None\n+222,uuid2,None\n"
    mock_file_system["exists"].return_value = True

    with patch('builtins.open', mock_open(read_data=existing_members_csv)):
        with patch('plugins.welcome.main.save_members') as mock_save_members:
            await group_info_handler(GROUP_INFO_DATA)

            # No welcome message should be sent
            mock_messaging_welcome["send_signal_group_message"].assert_not_called()
            # Members should still be re-saved (to keep the list fresh)
            mock_save_members.assert_called_once()


# --- Tests for cmd_initgroup ---

@pytest.mark.asyncio
async def test_cmd_initgroup(mock_messaging_welcome, mock_file_system):
    chat_id = "group123"

    # This is a bit complex because of the callback/future mechanism
    # We can simplify by patching the future directly
    async def mock_get_group_info(group_id, callback):
        await callback(GROUP_INFO_DATA)

    mock_messaging_welcome["get_group_info"].side_effect = mock_get_group_info

    with patch('plugins.welcome.main.save_members') as mock_save_members:
        response, _ = await cmd_initgroup(chat_id, [], None)
        assert f"initialized group {chat_id}" in response
        mock_save_members.assert_called_once()
        members = mock_save_members.call_args[0][1]
        assert len(members) == 2
        assert members[0].number == "+111"


# --- Helper Function Tests ---

def test_extract_members():
    members = extract_members(GROUP_INFO_DATA)
    assert len(members) == 2
    assert isinstance(members[0], Member)
    assert members[0].number == "+111"
    assert members[1].uuid == "uuid2"

def test_find_new_members(mock_file_system):
    chat_id = "group123"
    current_members = [
        Member(number="+111", uuid="uuid1"),
        Member(number="+333", uuid="uuid3"), # New member
    ]
    # Simulate existing members file
    existing_members_csv = "+111,uuid1,None\n+222,uuid2,None\n"
    mock_file_system["exists"].return_value = True

    with patch('builtins.open', mock_open(read_data=existing_members_csv)):
        new_members = find_new_members(chat_id, current_members)
        assert len(new_members) == 1
        assert new_members[0].number == "+333"

def test_save_members(mock_file_system):
    chat_id = "group123"
    members_to_save = [
        Member(number="+111", uuid="uuid1", username="User1"),
        Member(number="+222", uuid="uuid2", username=None),
    ]
    save_members(chat_id, members_to_save)

    # Check that open was called with the correct path and 'w' mode
    mock_file_system["open"].assert_called_once()
    # Check the content that was written
    handle = mock_file_system["open"].return_value.__enter__.return_value
    assert handle.write.call_count == 2
    handle.write.assert_any_call("+111,uuid1,User1\n")
    handle.write.assert_any_call("+222,uuid2,None\n")
