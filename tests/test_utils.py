
import os
import json
import shutil
from collections import deque
from unittest.mock import patch, mock_open
from datatypes import Attachment, ChatMessage, Permissions
from utils import (
    get_safe_chat_dir,
    get_local_file_store_path,
    get_local_files,
    get_permissions_file,
    load_permissions,
    save_permissions,
    check_permission,
    update_chat_history,
    get_chat_id,
    save_attachment,
)


def test_get_safe_chat_dir():
    base_path = "/tmp"
    chat_id = "test_chat"
    expected_path = os.path.join(base_path, "a8a556ee27e00844ef8f7df1579fea0a57a0fff0a3c2b8e80ae181b555e33c8e")
    assert get_safe_chat_dir(base_path, chat_id) == expected_path


def test_get_local_file_store_path():
    chat_id = "test_chat"
    with patch("utils.settings.file_store_path", "/tmp/files"):
        expected_path = get_safe_chat_dir("/tmp/files", chat_id)
        assert get_local_file_store_path(chat_id) == expected_path


def test_get_local_files():
    chat_id = "test_chat"
    chat_dir = get_local_file_store_path(chat_id)
    os.makedirs(chat_dir, exist_ok=True)
    with open(os.path.join(chat_dir, "test1.txt"), "w") as f:
        f.write("test1")
    with open(os.path.join(chat_dir, "test2.txt"), "w") as f:
        f.write("test2")
    expected_files = ["test1.txt", "test2.txt"]
    assert sorted(get_local_files(chat_id)) == sorted(expected_files)
    shutil.rmtree(chat_dir)


def test_get_permissions_file():
    chat_id = "test_chat"
    with patch("utils.settings.permissions_store_path", "/tmp/perms"):
        chat_dir = get_safe_chat_dir("/tmp/perms", chat_id)
        expected_file = os.path.join(chat_dir, "permissions.json")
        assert get_permissions_file(chat_id) == expected_file
        assert os.path.exists(chat_dir)
        shutil.rmtree(chat_dir)


def test_load_permissions():
    chat_id = "test_chat"
    perms_file = get_permissions_file(chat_id)
    os.makedirs(os.path.dirname(perms_file), exist_ok=True)
    perms_data = {"users": {"user1": ["command1"]}, "groups": {"ALL": {"members": [], "permissions": []}}}
    with open(perms_file, "w") as f:
        json.dump(perms_data, f)
    loaded_perms = load_permissions(chat_id)
    assert loaded_perms == perms_data
    os.remove(perms_file)
    shutil.rmtree(os.path.dirname(perms_file))


def test_save_permissions():
    chat_id = "test_chat"
    perms_data = {"users": {"user1": ["command1"]}, "groups": {"ALL": {"members": [], "permissions": []}}}
    save_permissions(chat_id, perms_data)
    perms_file = get_permissions_file(chat_id)
    with open(perms_file, "r") as f:
        saved_perms = json.load(f)
    assert saved_perms == perms_data
    os.remove(perms_file)
    shutil.rmtree(os.path.dirname(perms_file))


def test_check_permission():
    chat_id = "test_chat"
    sender = "user1"
    command = "command1"

    # Test superuser
    with patch("utils.settings.superuser", "user1"):
        assert check_permission(chat_id, sender, command)

    # Test direct user permission
    perms = {"users": {"user1": ["command1"]}, "groups": {}}
    with patch("utils.load_permissions", return_value=perms):
        assert check_permission(chat_id, sender, command)

    # Test group permission
    perms = {"users": {}, "groups": {"group1": {"members": ["user1"], "permissions": ["command1"]}}}
    with patch("utils.load_permissions", return_value=perms):
        assert check_permission(chat_id, sender, command)

    # Test ALL group permission
    perms = {"users": {}, "groups": {"ALL": {"permissions": ["command1"]}}}
    with patch("utils.load_permissions", return_value=perms):
        assert check_permission(chat_id, sender, command)

    # Test no permission
    perms = {"users": {}, "groups": {}}
    with patch("utils.load_permissions", return_value=perms):
        assert not check_permission(chat_id, sender, command)


def test_update_chat_history():
    chat_id = "test_chat"
    msg = ChatMessage(source=chat_id, text="Hello")
    with patch("utils.CHAT_HISTORY", {}):
        with patch("utils.settings.history_max_length", 2):
            update_chat_history(msg)
            from utils import CHAT_HISTORY
            assert msg.chat_id in CHAT_HISTORY
            assert len(CHAT_HISTORY[msg.chat_id]) == 1
            assert CHAT_HISTORY[msg.chat_id][0] == msg


def test_get_chat_id():
    # Test with group chat
    data = {"params": {"envelope": {"dataMessage": {"groupInfo": {"groupId": "group123"}}}}}
    assert get_chat_id(data) == "group123"

    # Test with direct message
    data = {"params": {"envelope": {"source": "user123"}}}
    assert get_chat_id(data) == "user123"

    # Test with sync message
    data = {"params": {"envelope": {"syncMessage": {"sentMessage": {"groupInfo": {"groupId": "group456"}}}}}}
    assert get_chat_id(data) == "group456"


def test_save_attachment():
    att = Attachment(id="att1", filename="test.txt", content_type="text/plain", size=1)
    dest_dir = "/tmp/attachments"
    os.makedirs(dest_dir, exist_ok=True)

    with patch("utils.settings.signal_attachments_path", "/tmp/signal_attachments"):
        signal_attachments_path = "/tmp/signal_attachments"
        os.makedirs(signal_attachments_path, exist_ok=True)
        src_file = os.path.join(signal_attachments_path, "att1")
        with open(src_file, "w") as f:
            f.write("test attachment")

        # Test with filename
        dest_file = save_attachment(att, dest_dir)
        assert dest_file and os.path.exists(dest_file)
        with open(dest_file, "r") as f:
            assert f.read() == "test attachment"
        os.remove(dest_file)

        # Test without filename
        att.filename = None
        dest_file = save_attachment(att, dest_dir)
        assert dest_file and os.path.exists(dest_file)
        os.remove(dest_file)

        shutil.rmtree(signal_attachments_path)

    shutil.rmtree(dest_dir)
