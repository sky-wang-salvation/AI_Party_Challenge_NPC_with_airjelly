from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .config import ServerConfig
from .protocol import ALLOWED_ACTIONS, ALLOWED_EXPRESSIONS
from .utils import extract_json_object, run_blocking


@dataclass
class LlmDirective:
    reply_text: str
    action: str
    expression: str


class BaseChatClient:
    provider_name = "none"

    def __init__(self, config: ServerConfig) -> None:
        self.config = config

    def is_available(self) -> bool:
        return False

    async def generate_directive(self, system_prompt: str, user_prompt: str) -> LlmDirective:
        raise NotImplementedError

    def _parse_directive_payload(self, raw_content: str, provider_label: str) -> LlmDirective:
        structured = extract_json_object(str(raw_content or ""))
        reply_text = str(structured.get("reply") or "").strip()
        action = str(structured.get("action") or "").strip()
        expression = str(structured.get("expression") or "").strip()

        if action not in ALLOWED_ACTIONS:
            raise RuntimeError(f"{provider_label} returned unsupported action: {action}")
        if expression not in ALLOWED_EXPRESSIONS:
            raise RuntimeError(f"{provider_label} returned unsupported expression: {expression}")
        if not reply_text:
            raise RuntimeError(f"{provider_label} returned empty reply")

        return LlmDirective(reply_text=reply_text, action=action, expression=expression)

    def _decode_json_response(self, response: Any) -> Dict[str, Any]:
        try:
            return json.loads(response.read().decode("utf-8"))
        finally:
            response.close()

    def _raise_http_error(self, exc: HTTPError, provider_label: str) -> None:
        detail = exc.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"{provider_label} HTTPError: {detail or exc.reason}")


class StepFunChatClient(BaseChatClient):
    provider_name = "stepfun"

    def is_available(self) -> bool:
        return bool(self.config.step_api_key.strip())

    async def generate_directive(self, system_prompt: str, user_prompt: str) -> LlmDirective:
        if not self.is_available():
            raise RuntimeError("STEP_API_KEY is not configured")
        return await run_blocking(self._call_api, system_prompt, user_prompt)

    def _call_api(self, system_prompt: str, user_prompt: str) -> LlmDirective:
        body = {
            "model": self.config.step_llm_model,
            "max_tokens": 220,
            "temperature": 0.4,
            "messages": [
                {
                    "role": "system",
                    "content": system_prompt,
                },
                {
                    "role": "user",
                    "content": user_prompt,
                },
            ],
        }
        request = Request(
            url=self.config.step_base_url.rstrip("/") + "/chat/completions",
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer " + self.config.step_api_key,
            },
            method="POST",
        )
        try:
            response = urlopen(request, timeout=self.config.llm_timeout_s)
            payload = self._decode_json_response(response)
        except HTTPError as exc:
            self._raise_http_error(exc, "StepFun chat")
        except URLError as exc:
            raise RuntimeError(f"StepFun chat URLError: {exc.reason}")

        choices = payload.get("choices", []) or []
        message = choices[0].get("message", {}) if choices else {}
        content = message.get("content", "")

        if isinstance(content, list):
            text_fragments = []
            for block in content:
                if isinstance(block, dict):
                    text_fragments.append(str(block.get("text") or block.get("content") or ""))
            content = "".join(text_fragments)

        return self._parse_directive_payload(str(content or ""), "StepFun")


class OpenAIResponsesClient(BaseChatClient):
    provider_name = "openai"

    def is_available(self) -> bool:
        return bool(self.config.openai_api_key.strip())

    async def generate_directive(self, system_prompt: str, user_prompt: str) -> LlmDirective:
        if not self.is_available():
            raise RuntimeError("OPENAI_API_KEY is not configured")
        return await run_blocking(self._call_api, system_prompt, user_prompt)

    def _call_api(self, system_prompt: str, user_prompt: str) -> LlmDirective:
        body: Dict[str, Any] = {
            "model": self.config.openai_model,
            "instructions": system_prompt,
            "input": user_prompt,
            "max_output_tokens": 220,
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "ktv_directive",
                    "strict": True,
                    "schema": {
                        "type": "object",
                        "properties": {
                            "reply": {"type": "string"},
                            "action": {"type": "string", "enum": list(ALLOWED_ACTIONS)},
                            "expression": {"type": "string", "enum": list(ALLOWED_EXPRESSIONS)},
                        },
                        "required": ["reply", "action", "expression"],
                        "additionalProperties": False,
                    },
                }
            },
        }

        if self.config.openai_reasoning_effort:
            body["reasoning"] = {"effort": self.config.openai_reasoning_effort}

        request = Request(
            url=self.config.openai_base_url.rstrip("/") + "/responses",
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer " + self.config.openai_api_key,
            },
            method="POST",
        )

        try:
            response = urlopen(request, timeout=self.config.llm_timeout_s)
            payload = self._decode_json_response(response)
        except HTTPError as exc:
            self._raise_http_error(exc, "OpenAI responses")
        except URLError as exc:
            raise RuntimeError(f"OpenAI responses URLError: {exc.reason}")

        content = self._extract_output_text(payload)
        return self._parse_directive_payload(content, "OpenAI")

    def _extract_output_text(self, payload: Dict[str, Any]) -> str:
        output_text = payload.get("output_text")
        if isinstance(output_text, str) and output_text.strip():
            return output_text

        fragments = []
        for item in payload.get("output", []) or []:
            if not isinstance(item, dict):
                continue

            content_blocks = item.get("content", [])
            if isinstance(content_blocks, dict):
                content_blocks = [content_blocks]

            for block in content_blocks:
                if not isinstance(block, dict):
                    continue
                if isinstance(block.get("text"), str) and block.get("text").strip():
                    fragments.append(block["text"])
                    continue
                if isinstance(block.get("output_text"), str) and block.get("output_text").strip():
                    fragments.append(block["output_text"])
                    continue
                if "json" in block:
                    fragments.append(json.dumps(block["json"], ensure_ascii=False))

        content = "".join(fragments).strip()
        if not content:
            raise RuntimeError("OpenAI returned empty content")
        return content


class KtvLlmClient:
    def __init__(self, config: ServerConfig) -> None:
        self.config = config
        self.client = self._select_client()

    @property
    def provider_name(self) -> str:
        return self.client.provider_name

    def _select_client(self) -> BaseChatClient:
        provider = (self.config.llm_provider or "auto").strip().lower()

        if provider == "openai":
            return OpenAIResponsesClient(self.config)
        if provider == "stepfun":
            return StepFunChatClient(self.config)
        if provider != "auto":
            raise ValueError(f"Unsupported llm provider: {self.config.llm_provider}")

        if self.config.openai_api_key.strip():
            return OpenAIResponsesClient(self.config)
        return StepFunChatClient(self.config)

    def is_available(self) -> bool:
        return self.client.is_available()

    async def generate_directive(self, system_prompt: str, user_prompt: str) -> LlmDirective:
        return await self.client.generate_directive(system_prompt, user_prompt)
