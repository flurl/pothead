
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

# Mock the google.genai library before it's imported by the plugin
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
    import plugins.gemini.main
    gemini_module = plugins.gemini.main
    from plugins.gemini.main import GeminiProvider, action_send_to_gemini
    from datatypes import ChatMessage, MessageQuote


@pytest.mark.asyncio
async def test_gemini_provider_get_response():
    with patch.object(GeminiProvider, 'client', new_callable=PropertyMock) as mock_client_prop:
        mock_client_instance = MagicMock()
        mock_client_prop.return_value = mock_client_instance
        mock_client_instance.aio.models.generate_content = AsyncMock(
            return_value=MagicMock(text="Test response"))

        provider = GeminiProvider(api_key="test_key")
        response = await provider.get_response("test_chat", "Test prompt")

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
        # Ensure the async method is mocked with AsyncMock to allow 'await'
        mock_client_instance.aio.models.generate_content = AsyncMock(
            return_value=MagicMock(text="Mocked Gemini Response"))
        mock_client_prop.return_value = mock_client_instance

        yield {
            "get_response": mock_get_response,
            "client": mock_client_instance
        }


@pytest.fixture
def mock_messaging():
    """Fixture to mock the messaging functions."""
    with patch.object(gemini_module, 'send_signal_direct_message', new_callable=AsyncMock) as mock_direct, \
            patch.object(gemini_module, 'send_signal_group_message', new_callable=AsyncMock) as mock_group:
        yield {"direct": mock_direct, "group": mock_group}


# --- Test Data ---

DATA_MESSAGE_DIRECT = {
    "params": {
        "envelope": {
            "source": "+12345", "sourceDevice": 1,
            "dataMessage": {
                "message": "!ph How are you?",
                "groupInfo": {}
            }
        }
    }
}
DATA_MESSAGE_GROUP = {
    "params": {
        "envelope": {
            "source": "+12345", "sourceDevice": 1,
            "dataMessage": {
                "message": "!ph How are you?",
                "groupInfo": {"groupId": "group123"}
            }
        }
    }
}


@pytest.mark.asyncio
@patch.object(gemini_module, 'settings')
async def test_action_send_to_gemini(mock_settings, mock_gemini_provider, mock_messaging):
    # Use a trigger word that matches the test data
    mock_settings.trigger_words = ["!ph"]

    # --- Test direct message ---
    await action_send_to_gemini(DATA_MESSAGE_DIRECT)

    msg_direct = ChatMessage.from_json(DATA_MESSAGE_DIRECT)
    prompt_direct = "How are you?"

    mock_gemini_provider["get_response"].assert_called_once_with(
        msg_direct.chat_id, prompt_direct)
    mock_messaging["direct"].assert_called_once_with(
        "Mocked Gemini Response", msg_direct.chat_id)
    assert not mock_messaging["group"].called
    mock_gemini_provider["get_response"].reset_mock()
    mock_messaging["direct"].reset_mock()

    # --- Test group message ---
    await action_send_to_gemini(DATA_MESSAGE_GROUP)

    msg_group = ChatMessage.from_json(DATA_MESSAGE_GROUP)
    prompt_group = "How are you?"

    mock_gemini_provider["get_response"].assert_called_once_with(
        msg_group.chat_id, prompt_group)
    mock_messaging["group"].assert_called_once_with(
        "Mocked Gemini Response", msg_group.chat_id)
    assert not mock_messaging["direct"].called
    mock_gemini_provider["get_response"].reset_mock()
    mock_messaging["group"].reset_mock()

    # --- Test with quote ---
    msg_with_quote_data = DATA_MESSAGE_DIRECT.copy()
    msg_with_quote_data["params"]["envelope"]["dataMessage"]["quote"] = {
        "text": "This is a quoted message."}
    await action_send_to_gemini(msg_with_quote_data)

    msg_quoted = ChatMessage.from_json(msg_with_quote_data)
    expected_prompt = f"{prompt_direct}\n\n>> This is a quoted message."

    mock_gemini_provider["get_response"].assert_called_once_with(
        msg_quoted.chat_id, expected_prompt)
    mock_gemini_provider["get_response"].reset_mock()
