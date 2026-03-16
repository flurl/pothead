
import pytest
import copy
from collections import deque
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock, mock_open

# Mock the google.genai library before it's imported by the plugin
import copy
google_mock = MagicMock()
google_mock.genai = MagicMock()
google_mock.genai.client = MagicMock()
google_mock.genai.types = MagicMock()
google_mock.genai.pagers = MagicMock()

gemini_module = None

with patch.dict('sys.modules', {
    'google': google_mock,
    'google.genai': google_mock.genai,
    'google.genai.client': google_mock.genai.client,
    'google.genai.types': google_mock.genai.types,
    'google.genai.pagers': google_mock.genai.pagers
}):
    import plugins.gemini.main as gemini_main_module
    gemini_module = gemini_main_module
    from plugins.gemini.main import (
        GeminiProvider,
        _should_process,
        on_chat_message,
        image_to_part,
        chat_with_gemini,
        cmd_add_ctx,
        cmd_ls_ctx,
        cmd_clear_ctx,
        cmd_ls_file_store,
        cmd_sync_store,
        cmd_save_sys,
        load_sys_instructions,
        save_sys_instructions
    )
    from datatypes import ChatMessage, Mention, MessageQuote, MessageType


def test_image_to_part():
    mock_img = MagicMock()
    mock_img.mode = 'RGB'

    with patch('plugins.gemini.main.io.BytesIO') as mock_bytesio:
        with patch('plugins.gemini.main.Image.open', return_value=mock_img) as mock_open:
            # We must also mock the exception handling or the try block correctly.
            # Actually, it seems Image.open is failing with FileNotFoundError even if mocked?
            # Ah, maybe I should patch 'PIL.Image.open' instead?
            # But the plugin does 'from PIL import Image'.

            # Let's try patching it where it's used in the plugin's namespace.
            with patch.object(gemini_module, 'Image') as mock_PIL_Image:
                mock_PIL_Image.open.return_value = mock_img
                result = image_to_part("test_path.jpg")

                assert result is not None
                google_mock.genai.types.Part.assert_called()
                mock_img.save.assert_called()


@pytest.mark.asyncio
async def test_gemini_provider_get_response():
    with patch.object(GeminiProvider, 'client', new_callable=PropertyMock) as mock_client_prop:
        mock_client_instance = MagicMock()
        mock_client_prop.return_value = mock_client_instance
        mock_client_instance.aio.models.generate_content = AsyncMock(
            return_value=MagicMock(text="Test response"))

        provider = GeminiProvider(api_key="test_key")
        mock_part = MagicMock()
        response = await provider.get_response("test_chat", [mock_part])

        assert response == "Test response"
        mock_client_instance.aio.models.generate_content.assert_called_once()

# --- Fixtures ---


@pytest.fixture
def mock_gemini_provider():
    """Fixture to mock the GeminiProvider's async methods."""
    with patch.object(gemini_module.gemini, 'get_response', new_callable=AsyncMock) as mock_get_response, \
            patch.object(GeminiProvider, 'client', new_callable=PropertyMock) as mock_client_prop:
        mock_get_response.return_value = "Mocked Gemini Response"
        mock_client_instance = MagicMock()
        mock_client_prop.return_value = mock_client_instance
        yield {
            "get_response": mock_get_response,
            "client": mock_client_instance
        }


@pytest.fixture
def mock_messaging():
    """Fixture to mock the messaging send function."""
    with patch.object(gemini_module, 'send_signal_message', new_callable=AsyncMock) as mock_send:
        yield {"send": mock_send}


# --- Helpers ---

def make_chat_msg(text=None, source="+12345", destination=None, group_id=None,
                  quote_text=None, attachments=None, mentions=None):
    quote = MessageQuote(id=1, author=source, author_number=source, author_uuid="u",
                         text=quote_text) if quote_text else None
    return ChatMessage(
        source=source, source_name=source,
        destination=destination, group_id=group_id,
        text=text, type=MessageType.CHAT, timestamp=1678886400000,
        quote=quote, attachments=attachments, mentions=mentions,
    )


# --- Tests for _should_process (trigger word mode) ---

def test_should_process_trigger_match():
    with patch.object(gemini_module.settings, 'trigger_words', ["!ping"]), \
         patch.object(gemini_module.settings, 'dedicated_account', False):
        msg = make_chat_msg(text="!ping How are you?")
        assert _should_process(msg)


def test_should_process_trigger_no_match():
    with patch.object(gemini_module.settings, 'trigger_words', ["!ping"]), \
         patch.object(gemini_module.settings, 'dedicated_account', False):
        msg = make_chat_msg(text="hello world")
        assert not _should_process(msg)


def test_should_process_trigger_attachment_only_no_trigger():
    """Attachment-only message without a trigger word should not process in shared account mode."""
    with patch.object(gemini_module.settings, 'trigger_words', ["!ping"]), \
         patch.object(gemini_module.settings, 'dedicated_account', False):
        from datatypes import Attachment
        msg = make_chat_msg(text="", attachments=[Attachment(id="a1", content_type="image/jpeg", size=1)])
        assert not _should_process(msg)


# --- Tests for _should_process (dedicated_account mode) ---

def test_should_process_dedicated_is_recipient():
    with patch.object(gemini_module.settings, 'dedicated_account', True), \
         patch.object(gemini_module.settings, 'signal_account', "+bot"):
        msg = make_chat_msg(text="Hello bot", destination="+bot")
        assert _should_process(msg)


def test_should_process_dedicated_is_mentioned():
    with patch.object(gemini_module.settings, 'dedicated_account', True), \
         patch.object(gemini_module.settings, 'signal_account', "+bot"):
        mention = Mention(number="+bot", uuid="bot-uuid", start=0, length=1)
        msg = make_chat_msg(text="hey bot", group_id="group1", mentions=[mention])
        assert _should_process(msg)


def test_should_process_dedicated_not_recipient_not_mentioned():
    with patch.object(gemini_module.settings, 'dedicated_account', True), \
         patch.object(gemini_module.settings, 'signal_account', "+bot"):
        msg = make_chat_msg(text="just a group message", destination="+other", group_id="group1")
        assert not _should_process(msg)


def test_should_process_dedicated_mention_wrong_number():
    with patch.object(gemini_module.settings, 'dedicated_account', True), \
         patch.object(gemini_module.settings, 'signal_account', "+bot"):
        mention = Mention(number="+someone_else", uuid="uuid", start=0, length=1)
        msg = make_chat_msg(text="hey", group_id="group1", mentions=[mention])
        assert not _should_process(msg)


# --- Tests for on_chat_message event handler ---

@pytest.mark.asyncio
async def test_on_chat_message_direct(mock_gemini_provider, mock_messaging):
    with patch.object(gemini_module.settings, 'trigger_words', ["!ping"]), \
         patch.object(gemini_module.settings, 'dedicated_account', False):
        msg = make_chat_msg(text="!ping How are you?", source="+12345", destination="+12345")
        with patch.dict(gemini_module.CHAT_HISTORY, {"+12345": deque([msg])}, clear=False):
            await on_chat_message(msg)

            mock_gemini_provider["get_response"].assert_called_once()
            mock_messaging["send"].assert_called_once()
            sent = mock_messaging["send"].call_args[0][0]
            assert sent.destination == "+12345"
            assert sent.group_id is None
            assert sent.is_outgoing is True


@pytest.mark.asyncio
async def test_on_chat_message_group(mock_gemini_provider, mock_messaging):
    with patch.object(gemini_module.settings, 'trigger_words', ["!ping"]), \
         patch.object(gemini_module.settings, 'dedicated_account', False):
        msg = make_chat_msg(text="!ping How are you?", source="+12345", group_id="group123")
        with patch.dict(gemini_module.CHAT_HISTORY, {"group123": deque([msg])}, clear=False):
            await on_chat_message(msg)

            args, _ = mock_gemini_provider["get_response"].call_args
            assert args[0] == "group123"
            mock_messaging["send"].assert_called_once()
            sent = mock_messaging["send"].call_args[0][0]
            assert sent.group_id == "group123"
            assert sent.is_outgoing is True


@pytest.mark.asyncio
async def test_on_chat_message_with_quote(mock_gemini_provider, mock_messaging):
    with patch.object(gemini_module.settings, 'trigger_words', ["!ping"]), \
         patch.object(gemini_module.settings, 'dedicated_account', False):
        msg = make_chat_msg(text="!ping Ask this", source="+12345",
                            destination="+12345", quote_text="Quoted text")
        with patch.dict(gemini_module.CHAT_HISTORY, {"+12345": deque([msg])}, clear=False):
            await on_chat_message(msg)
            mock_gemini_provider["get_response"].assert_called_once()


@pytest.mark.asyncio
async def test_on_chat_message_no_trigger(mock_gemini_provider, mock_messaging):
    with patch.object(gemini_module.settings, 'trigger_words', ["!ping"]), \
         patch.object(gemini_module.settings, 'dedicated_account', False):
        msg = make_chat_msg(text="just a regular message")
        await on_chat_message(msg)
        mock_gemini_provider["get_response"].assert_not_called()


@pytest.mark.asyncio
async def test_on_chat_message_with_image(mock_gemini_provider, mock_messaging):
    with patch.object(gemini_module.settings, 'trigger_words', ["!ping"]), \
         patch.object(gemini_module.settings, 'dedicated_account', False), \
         patch('plugins.gemini.main.os.path.exists', return_value=True), \
         patch.object(gemini_module, 'image_to_part', side_effect=lambda x: MagicMock()) as mock_i2p:
        from datatypes import Attachment
        att = Attachment(id="att1", content_type="image/jpeg", size=100)
        msg = make_chat_msg(text="!ping look at this", source="+12345",
                            destination="+12345", attachments=[att])
        with patch.dict(gemini_module.CHAT_HISTORY, {"+12345": deque([msg])}, clear=False):
            await on_chat_message(msg)

            assert mock_i2p.called
            mock_gemini_provider["get_response"].assert_called_once()


@pytest.mark.asyncio
async def test_chat_with_gemini(mock_gemini_provider, mock_messaging):
    chat_id = "test_chat"
    history = deque([
        ChatMessage(source="user", source_name="user", destination=chat_id, text="Hello",
                    type=MessageType.CHAT, timestamp=1000),
        ChatMessage(source="Assistant", source_name="Assistant", destination=chat_id, text="Hi there",
                    type=MessageType.CHAT, timestamp=2000),
        ChatMessage(source="user", source_name="user", destination=chat_id, text="How are you?",
                    type=MessageType.CHAT, timestamp=3000),
    ])

    mock_history = {chat_id: history}
    with patch.dict(gemini_module.CHAT_HISTORY, mock_history, clear=True):
        await chat_with_gemini(chat_id)

        assert mock_gemini_provider["get_response"].called
        mock_messaging["send"].assert_called_once()
        sent = mock_messaging["send"].call_args[0][0]
        # last_msg.source is "user", chat_id for non-synced DM from "user" = "user"
        assert sent.destination == "user"
        assert sent.is_outgoing is True


@pytest.mark.asyncio
async def test_cmd_add_ctx():
    chat_id = "test_chat"
    history = deque([
        ChatMessage(source="user", source_name="user", destination=chat_id,
                    text="Message 1", type=MessageType.CHAT, timestamp=1000),
        ChatMessage(source="user", source_name="user", destination=chat_id,
                    text="Message 2", type=MessageType.CHAT, timestamp=2000),
        ChatMessage(source="user", source_name="user", destination=chat_id,
                    text="!gemini #addctx 1", type=MessageType.CHAT, timestamp=3000),
    ])

    # Try direct modification of the dictionary in the module
    with patch.dict(gemini_module.CHAT_HISTORY, {chat_id: history}, clear=True):
        # Mock gemini.get_chat_context to return a list we can check
        context = []
        with patch.object(gemini_module.gemini, 'get_chat_context', return_value=context):
            # idx=1 should refer to "Message 2" (one before the command)
            response, _ = await cmd_add_ctx(chat_id, ["1"], "Manual prompt")

            assert "Context saved (2 items)" in response
            assert len(context) == 2
            # history[-(1+1)] should be Message 2
            assert "Message 2" in context[0]
            assert "Manual prompt" in context[1]


@pytest.mark.asyncio
async def test_cmd_ls_ctx():
    chat_id = "test_chat"
    context = ["Item 1", "Item 2 with many words that should be truncated"]
    with patch.object(gemini_module.gemini, 'get_chat_context', return_value=context):
        response, _ = await cmd_ls_ctx(chat_id, [], None)
        assert "📝 Current Context:" in response
        assert "Item 1" in response
        assert "Item 2 with many words..." in response


@pytest.mark.asyncio
async def test_cmd_clear_ctx():
    chat_id = "test_chat"
    context = ["Item 1"]
    with patch.object(gemini_module.gemini, 'get_chat_context', return_value=context):
        response, _ = await cmd_clear_ctx(chat_id, [], None)
        assert "🗑️ Context cleared." in response
        assert len(context) == 0


@pytest.mark.asyncio
async def test_cmd_ls_file_store(mock_gemini_provider):
    chat_id = "test_chat"
    mock_store = MagicMock()
    mock_store.name = "stores/test-store"
    mock_gemini_provider["client"].file_search_stores.documents.list.return_value = [
        MagicMock(display_name="file1.txt"),
        MagicMock(display_name="file2.pdf")
    ]

    with patch.object(gemini_module.gemini, 'get_chat_store', return_value=mock_store):
        response, _ = await cmd_ls_file_store(chat_id, [], None)
        assert "Gemini's File Store" in response
        assert "- file1.txt" in response
        assert "- file2.pdf" in response


@pytest.mark.asyncio
async def test_cmd_sync_store(mock_gemini_provider):
    chat_id = "test_chat"
    mock_store = MagicMock()
    mock_store.name = "stores/test-store"

    mock_upload_op = MagicMock()
    mock_upload_op.done = True
    mock_gemini_provider["client"].file_search_stores.upload_to_file_search_store.return_value = mock_upload_op

    with patch.object(gemini_module.gemini, 'get_chat_store', return_value=mock_store), \
            patch('plugins.gemini.main.get_local_files', return_value=["file1.txt"]), \
            patch('plugins.gemini.main.os.path.isdir', return_value=True), \
            patch('plugins.gemini.main.os.listdir', return_value=["file1.txt"]), \
            patch('plugins.gemini.main.os.path.isfile', return_value=True):
        response, _ = await cmd_sync_store(chat_id, [], None)
        assert "Synced 1 files" in response
        mock_gemini_provider["client"].file_search_stores.upload_to_file_search_store.assert_called_once(
        )


@pytest.mark.asyncio
async def test_cmd_save_sys():
    chat_id = "test_chat"

    # Ensure clean state
    gemini_module.custom_sys_instructions.clear()

    with patch.object(gemini_module, 'save_sys_instructions') as mock_save:
        # 1. Set new instruction
        response, _ = await cmd_save_sys(chat_id, [], "New instruction")
        assert "saved" in response
        assert gemini_module.custom_sys_instructions[chat_id] == "New instruction"
        mock_save.assert_called_once()
        mock_save.reset_mock()

        # 2. Update instruction
        response, _ = await cmd_save_sys(chat_id, [], "Updated instruction")
        assert "saved" in response
        assert gemini_module.custom_sys_instructions[chat_id] == "Updated instruction"
        mock_save.assert_called_once()
        mock_save.reset_mock()

        # 3. Remove instruction
        response, _ = await cmd_save_sys(chat_id, [], None)
        assert "removed" in response
        assert chat_id not in gemini_module.custom_sys_instructions
        mock_save.assert_called_once()
        mock_save.reset_mock()

        # 4. Remove non-existent
        response, _ = await cmd_save_sys(chat_id, [], None)
        assert "No custom system instruction" in response
        mock_save.assert_not_called()


def test_load_sys_instructions():
    # Test loading valid JSON
    mock_data = '{"chat1": "instr1"}'
    with patch('os.path.exists', return_value=True):
        with patch('builtins.open', mock_open(read_data=mock_data)):
            load_sys_instructions()
            assert gemini_module.custom_sys_instructions == {"chat1": "instr1"}

    # Test missing file
    gemini_module.custom_sys_instructions = {}
    with patch('os.path.exists', return_value=False):
        load_sys_instructions()
        assert gemini_module.custom_sys_instructions == {}

    # Test invalid JSON
    with patch('os.path.exists', return_value=True):
        with patch('builtins.open', mock_open(read_data="invalid json")):
            with patch.object(gemini_module, 'logger') as mock_logger:
                load_sys_instructions()
                mock_logger.error.assert_called()


def test_save_sys_instructions():
    gemini_module.custom_sys_instructions = {"chat1": "instr1"}
    with patch('builtins.open', mock_open()) as mock_file:
        save_sys_instructions()
        mock_file.assert_called_once()
        mock_file.assert_called_with(
            gemini_module.SYS_INSTRUCTIONS_FILE, "w", encoding="utf-8")
