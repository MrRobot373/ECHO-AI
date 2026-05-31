from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator

import httpx

from backend.config import Settings
from backend.pipeline.errors import ComponentUnavailable


_SENTENCE_RE = re.compile(r"(.+?[.!?])(\s+|$)")


def pop_complete_sentences(buffer: str) -> tuple[list[str], str]:
    sentences: list[str] = []
    consumed = 0
    for match in _SENTENCE_RE.finditer(buffer):
        sentence = match.group(1).strip()
        if sentence:
            sentences.append(sentence)
        consumed = match.end()
    return sentences, buffer[consumed:].lstrip()


class OllamaClient:
    def __init__(self, settings: Settings):
        self.settings = settings

    def _options(self, *, num_predict: int | None = None, temperature: float | None = None) -> dict:
        options = {
            "temperature": self.settings.llm_temperature if temperature is None else temperature,
            "num_predict": self.settings.llm_num_predict if num_predict is None else num_predict,
        }
        if self.settings.ollama_num_ctx:
            options["num_ctx"] = self.settings.ollama_num_ctx
        if self.settings.ollama_num_thread:
            options["num_thread"] = self.settings.ollama_num_thread
        return options

    async def stream_response(self, prompt: str) -> AsyncIterator[str]:
        payload = {
            "model": self.settings.ollama_model,
            "prompt": prompt,
            "system": self.settings.system_prompt,
            "stream": True,
            "keep_alive": self.settings.ollama_keep_alive,
            "options": self._options(),
        }

        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=5.0)) as client:
                async with client.stream("POST", self.settings.ollama_url, json=payload) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        if not line:
                            continue
                        data = json.loads(line)
                        chunk = data.get("response", "")
                        if chunk:
                            yield chunk
                        if data.get("done"):
                            break
        except httpx.HTTPError as exc:
            raise ComponentUnavailable(
                f"Ollama is unavailable at {self.settings.ollama_url}. "
                f"Start Ollama and pull {self.settings.ollama_model}."
            ) from exc

    async def chat_with_tools(
        self,
        user_text: str,
        tools: list[dict],
        system: str | None = None,
        history: list[dict] | None = None,
    ) -> tuple[str, list[dict]]:
        """Non-streaming /api/chat call that lets the model pick a tool.

        `history` is prior turns ([{role, content}, ...]) for multi-turn memory.
        Returns (content, tool_calls). tool_calls is a list of
        {"name": str, "arguments": dict}. Either may be empty.
        """
        messages = [{"role": "system", "content": system or self.settings.system_prompt}]
        messages.extend(history or [])
        messages.append({"role": "user", "content": user_text})
        payload = {
            "model": self.settings.ollama_tool_model,
            "messages": messages,
            "tools": tools,
            "stream": False,
            "keep_alive": self.settings.ollama_keep_alive,
            "options": self._options(num_predict=256, temperature=0.2),
        }
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                response = await client.post(self.settings.ollama_chat_url, json=payload)
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPError as exc:
            raise ComponentUnavailable(
                f"Ollama chat is unavailable at {self.settings.ollama_chat_url}. "
                f"Start Ollama and pull {self.settings.ollama_tool_model}."
            ) from exc

        message = data.get("message", {}) or {}
        content = (message.get("content") or "").strip()
        tool_calls: list[dict] = []
        for call in message.get("tool_calls", []) or []:
            function = call.get("function", {}) or {}
            name = function.get("name")
            if not name:
                continue
            arguments = function.get("arguments", {})
            if isinstance(arguments, str):
                try:
                    arguments = json.loads(arguments)
                except json.JSONDecodeError:
                    arguments = {}
            tool_calls.append({"name": name, "arguments": arguments or {}})
        return content, tool_calls

    async def warm_up(self) -> None:
        payload = {
            "model": self.settings.ollama_model,
            "prompt": "OK",
            "stream": False,
            "keep_alive": self.settings.ollama_keep_alive,
            "options": self._options(num_predict=1, temperature=0),
        }
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                response = await client.post(self.settings.ollama_url, json=payload)
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise ComponentUnavailable(
                f"Ollama warm-up failed at {self.settings.ollama_url}. "
                f"Start Ollama and pull {self.settings.ollama_model}."
            ) from exc

    async def warm_up_tool_model(self) -> None:
        """Preload the tool model so the first command isn't slow."""
        if self.settings.ollama_tool_model == self.settings.ollama_model:
            return
        payload = {
            "model": self.settings.ollama_tool_model,
            "messages": [{"role": "user", "content": "OK"}],
            "stream": False,
            "keep_alive": self.settings.ollama_keep_alive,
            "options": self._options(num_predict=1, temperature=0),
        }
        try:
            async with httpx.AsyncClient(timeout=120) as client:
                response = await client.post(self.settings.ollama_chat_url, json=payload)
                response.raise_for_status()
        except httpx.HTTPError:
            # non-fatal: routing will fall back to chat if the tool model is missing
            logger_warn = f"tool model {self.settings.ollama_tool_model} not ready"
            print(logger_warn)
