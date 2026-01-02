import abc
from config import settings
from google.genai.client import Client
from google.genai import types

from state import CHAT_CONTEXT, CHAT_STORES
from utils import get_chat_store


class AIProvider(abc.ABC):
    @abc.abstractmethod
    async def get_response(self, chat_id: str, prompt_text: str) -> str | None:
        pass

    @property
    @abc.abstractmethod
    def client(self) -> Client:
        pass


class GeminiProvider(AIProvider):
    def __init__(self, api_key: str):
        self._client: Client = Client(api_key=api_key)

    @property
    def client(self) -> Client:
        return self._client

    async def get_response(self, chat_id: str, prompt_text: str) -> str | None:
        """Sends text to Gemini and returns the response."""
        try:
            chat_store: types.FileSearchStore | None = get_chat_store(
                chat_id, CHAT_STORES, self.client)

            parts: list[types.Part] = []
            # Add context if available and withdraw it
            if chat_id in CHAT_CONTEXT:
                for ctx in CHAT_CONTEXT[chat_id]:
                    parts.append(types.Part(text=ctx))
                del CHAT_CONTEXT[chat_id]

            parts.append(types.Part(text=prompt_text))

            # Create a proper Content object for the prompt
            content = types.Content(parts=parts)

            tools: list[types.Tool] = []
            if chat_store and chat_store.name:
                tools.append(types.Tool(
                    file_search=types.FileSearch(
                        file_search_store_names=[chat_store.name]
                    )
                ))

            # Generate content
            response: types.GenerateContentResponse = await self.client.aio.models.generate_content(  # type: ignore
                model=settings.gemini_model_name,
                contents=content,
                config=types.GenerateContentConfig(
                    system_instruction=settings.system_instruction,
                    tools=tools if tools else None,
                    safety_settings=[
                        types.SafetySetting(
                            category=types.HarmCategory.HARM_CATEGORY_HARASSMENT,
                            threshold=types.HarmBlockThreshold.BLOCK_NONE
                        ),
                        types.SafetySetting(
                            category=types.HarmCategory.HARM_CATEGORY_HATE_SPEECH,
                            threshold=types.HarmBlockThreshold.BLOCK_NONE
                        ),
                        types.SafetySetting(
                            category=types.HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT,
                            threshold=types.HarmBlockThreshold.BLOCK_NONE
                        ),
                        types.SafetySetting(
                            category=types.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT,
                            threshold=types.HarmBlockThreshold.BLOCK_NONE
                        ),
                    ]
                ),
            )
            return response.text
        except Exception as e:
            return f"Error querying Gemini: {str(e)}"


def get_ai_provider() -> AIProvider:
    # For now, we only have GeminiProvider.
    # This function can be extended to support other providers.
    return GeminiProvider(api_key=settings.gemini_api_key)


AI_PROVIDER: AIProvider = get_ai_provider()
