
import asyncio
from collections import deque
from unittest.mock import AsyncMock, patch, mock_open
import pytest
from datatypes import ChatMessage, Command, MessageType, Permissions
from commands import (
    cmd_save,
    cmd_ls_store,
    cmd_getfile,
    cmd_grant,
    cmd_mkgroup,
    cmd_addmember,
    cmd_grantgroup,
    cmd_revoke,
    cmd_rmmember,
    cmd_revokegroup,
    cmd_rmgroup,
    cmd_lsperms,
    cmd_lsdirs,
    cmd_help,
    cmd_showchatid,
    COMMANDS,
)


@pytest.mark.asyncio
async def test_cmd_save():
    chat_id = "test_chat"
    prompt = "Test prompt"
    history = deque(
        [ChatMessage(source="user1", text="Message 1", type=MessageType.CHAT)])

    with patch("commands.CHAT_HISTORY", {chat_id: history}):
        with patch("builtins.open", mock_open()) as mock_file:
            with patch("commands.save_attachment", return_value=True):
                response, attachments = await cmd_save(chat_id, [], prompt)
                assert "Saved 1 text items" in response
                mock_file.assert_called_once()


@pytest.mark.asyncio
async def test_cmd_ls_store():
    chat_id = "test_chat"
    with patch("commands.get_local_files", return_value=["file1.txt", "file2.txt"]):
        response, _ = await cmd_ls_store(chat_id, [], None)
        assert "file1.txt" in response
        assert "file2.txt" in response


@pytest.mark.asyncio
async def test_cmd_getfile():
    chat_id = "test_chat"
    with patch("commands.get_local_files", return_value=["file1.txt"]):
        with patch("commands.get_safe_chat_dir", return_value="/tmp/chat"):
            response, attachments = await cmd_getfile(chat_id, ["1"], None)
            assert "Here is file1.txt" in response
            assert attachments == ["/tmp/chat/file1.txt"]


@pytest.mark.asyncio
async def test_cmd_grant():
    chat_id = "test_chat"
    params = ["help", "user1"]
    perms: Permissions = {"users": {}, "groups": {}}
    with patch("commands.load_permissions", return_value=perms):
        with patch("commands.save_permissions") as mock_save:
            response, _ = await cmd_grant(chat_id, params, None)
            assert "Granted 'help' to user1" in response
            mock_save.assert_called_once()


@pytest.mark.asyncio
async def test_cmd_mkgroup():
    chat_id = "test_chat"
    params = ["new_group"]
    perms: Permissions = {"users": {}, "groups": {}}
    with patch("commands.load_permissions", return_value=perms):
        with patch("commands.save_permissions") as mock_save:
            response, _ = await cmd_mkgroup(chat_id, params, None)
            assert "Group 'new_group' created" in response
            mock_save.assert_called_once()


@pytest.mark.asyncio
async def test_cmd_addmember():
    chat_id = "test_chat"
    params = ["my_group", "user1"]
    perms: Permissions = {"users": {}, "groups": {
        "my_group": {"members": [], "permissions": []}}}
    with patch("commands.load_permissions", return_value=perms):
        with patch("commands.save_permissions") as mock_save:
            response, _ = await cmd_addmember(chat_id, params, None)
            assert "Added user1 to group 'my_group'" in response
            mock_save.assert_called_once()


@pytest.mark.asyncio
async def test_cmd_grantgroup():
    chat_id = "test_chat"
    params = ["help", "my_group"]
    perms: Permissions = {"users": {}, "groups": {
        "my_group": {"members": [], "permissions": []}}}
    with patch("commands.load_permissions", return_value=perms):
        with patch("commands.save_permissions") as mock_save:
            response, _ = await cmd_grantgroup(chat_id, params, None)
            assert "Granted 'help' to group 'my_group'" in response
            mock_save.assert_called_once()


@pytest.mark.asyncio
async def test_cmd_revoke():
    chat_id = "test_chat"
    params = ["help", "user1"]
    perms: Permissions = {"users": {"user1": ["help"]}, "groups": {}}
    with patch("commands.load_permissions", return_value=perms):
        with patch("commands.save_permissions") as mock_save:
            response, _ = await cmd_revoke(chat_id, params, None)
            assert "Revoked 'help' from user1" in response
            mock_save.assert_called_once()


@pytest.mark.asyncio
async def test_cmd_rmmember():
    chat_id = "test_chat"
    params = ["my_group", "user1"]
    perms: Permissions = {"users": {}, "groups": {
        "my_group": {"members": ["user1"], "permissions": []}}}
    with patch("commands.load_permissions", return_value=perms):
        with patch("commands.save_permissions") as mock_save:
            response, _ = await cmd_rmmember(chat_id, params, None)
            assert "Removed user1 from group 'my_group'" in response
            mock_save.assert_called_once()


@pytest.mark.asyncio
async def test_cmd_revokegroup():
    chat_id = "test_chat"
    params = ["help", "my_group"]
    perms: Permissions = {"users": {}, "groups": {
        "my_group": {"members": [], "permissions": ["help"]}}}
    with patch("commands.load_permissions", return_value=perms):
        with patch("commands.save_permissions") as mock_save:
            response, _ = await cmd_revokegroup(chat_id, params, None)
            assert "Revoked 'help' from group 'my_group'" in response
            mock_save.assert_called_once()


@pytest.mark.asyncio
async def test_cmd_rmgroup():
    chat_id = "test_chat"
    params = ["my_group"]
    perms: Permissions = {"users": {}, "groups": {
        "my_group": {"members": [], "permissions": []}}}
    with patch("commands.load_permissions", return_value=perms):
        with patch("commands.save_permissions") as mock_save:
            response, _ = await cmd_rmgroup(chat_id, params, None)
            assert "Group 'my_group' deleted" in response
            mock_save.assert_called_once()


@pytest.mark.asyncio
async def test_cmd_lsperms():
    chat_id = "test_chat"
    perms: Permissions = {"users": {"user1": ["help"]}, "groups": {
        "my_group": {"members": ["user1"], "permissions": ["help"]}}}
    with patch("commands.load_permissions", return_value=perms):
        response, _ = await cmd_lsperms(chat_id, [], None)
        assert "user1: help" in response
        assert "my_group" in response


@pytest.mark.asyncio
async def test_cmd_lsdirs():
    chat_id = "test_chat"
    with patch("commands.get_safe_chat_dir", return_value="/tmp/chat"):
        response, _ = await cmd_lsdirs(chat_id, [], None)
        assert "/tmp/chat" in response


@pytest.mark.asyncio
async def test_cmd_help():
    response, _ = await cmd_help("test_chat", [], None)
    for command in COMMANDS:
        assert command.name in response
        assert command.help_text in response


@pytest.mark.asyncio
async def test_cmd_showchatid():
    chat_id = "test_chat"
    response, _ = await cmd_showchatid(chat_id, [], None)
    assert chat_id in response
