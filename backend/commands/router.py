"""Turn a transcript into either an executed action or a spoken answer.

Flow: ask the tool-capable model (with conversation history) to either pick a
tool or answer directly.
  - tool call  -> permission check -> run executor -> spoken confirmation
  - plain text -> return it as a conversational answer (spoken)
  - nothing    -> return None so the caller can fall back to streaming chat
"""
from __future__ import annotations

import asyncio
import logging

from backend.commands.executors import execute
from backend.commands.permissions import PermissionStore
from backend.commands.tools import TOOL_SPECS, required_permission
from backend.config import Settings
from backend.pipeline.errors import ComponentUnavailable

logger = logging.getLogger(__name__)

_PERMISSION_LABELS = {
    "volume_up": "volume", "volume_down": "volume", "car_info": "car info",
    "web_search": "web search",
}

_WEB_INTENT = ("search", "look up", "lookup", "google", "browse", "latest", "news",
               "price", "stock", "score", "headlines")


def _wants_web(text: str) -> bool:
    t = text.lower()
    return any(k in t for k in _WEB_INTENT)


_TOOL_GUIDANCE = (
    " You are an in-car voice assistant. Call a tool ONLY when the user wants an "
    "action (open, play, navigate, call, message, set volume/brightness, toggle a "
    "setting) or live data (weather). For general questions, knowledge, or chit-chat, "
    "DO NOT call a tool — just answer directly in one or two short, spoken sentences. "
    "Only use web_search when the user explicitly asks to search the web."
)


async def route(
    text: str,
    llm,
    settings: Settings,
    permissions: PermissionStore,
    history: list[dict] | None = None,
) -> str | None:
    """Return spoken text (action result or answer), or None to fall back."""
    system = settings.system_prompt + _TOOL_GUIDANCE
    try:
        content, tool_calls = await llm.chat_with_tools(text, TOOL_SPECS, system=system, history=history)
    except ComponentUnavailable as exc:
        logger.info("tool model unavailable, falling back to chat: %s", exc)
        return None
    except Exception as exc:  # noqa: BLE001
        logger.warning("tool routing failed, falling back to chat: %s", exc)
        return None

    if tool_calls:
        call = tool_calls[0]
        name = call["name"]
        args = call.get("arguments", {})

        # The model over-eagerly picks web_search for general knowledge. If the
        # user didn't actually ask to search, answer conversationally instead.
        if name == "web_search" and not _wants_web(text):
            answer = await _answer_directly(text, llm, settings, history)
            if answer:
                return answer

        perm = required_permission(name, args)
        if not permissions.allowed(perm):
            label = _PERMISSION_LABELS.get(perm, perm)
            return f"{label.capitalize()} is turned off in permissions."

        logger.info("executing tool=%s args=%s", name, args)
        try:
            return await asyncio.to_thread(execute, name, args, settings)
        except Exception as exc:  # noqa: BLE001
            logger.warning("executor %s failed: %s", name, exc)
            return settings.friendly_error

    # Conversational answer straight from the model.
    if content:
        return content
    return None


async def _answer_directly(text: str, llm, settings: Settings, history: list[dict] | None) -> str | None:
    """Second pass with no tools → a short spoken answer for general questions."""
    system = settings.system_prompt + " Answer in one or two short, spoken sentences."
    try:
        content, _ = await llm.chat_with_tools(text, [], system=system, history=history)
        return content or None
    except Exception as exc:  # noqa: BLE001
        logger.warning("direct answer failed: %s", exc)
        return None
