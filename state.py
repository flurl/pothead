from collections import deque
from google.genai import types

from datatypes import ChatMessage

CHAT_HISTORY: dict[str, deque[ChatMessage]] = {}
CHAT_LOCAL_STORES: dict[str, types.FileSearchStore] = {}
