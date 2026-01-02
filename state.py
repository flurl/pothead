from collections import deque
from google.genai import types

from datatypes import ChatMessage

CHAT_HISTORY: dict[str, deque[ChatMessage]] = {}
CHAT_CONTEXT: dict[str, list[str]] = {}
CHAT_STORES: dict[str, types.FileSearchStore] = {}
