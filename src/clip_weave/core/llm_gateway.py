"""Shared "call a chat-completion gateway" plumbing.

Both `workflow_router.py` (workflow classification) and `t2v_prompt.py` (T2V
scene rewriting) need the same three things: find a configured gateway from
environment variables, POST a chat completion, and retry in the Anthropic
`/v1/messages` dialect when the route turns out to be Bedrock-style and 404s on
`/chat/completions`. This module is that shared plumbing, factored out so the
retry-on-404 behaviour has exactly one implementation.

`workflow_router.py` predates this module and keeps its own copy inline (it has
its own test suite pinned to its exact call shape); new gateway callers should
use this module instead of copying the pattern a third time.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GatewayConfig:
    base_url: str
    api_key: str
    model: str


class NotOpenAICompatible(Exception):
    """The route exists but does not speak OpenAI chat/completions."""


def resolve_gateway(prefixes: tuple[tuple[str, str], ...]) -> GatewayConfig | None:
    """Return the first configured `(base_url, api_key, model)` from env vars.

    `prefixes` is an ordered list of `(ENV_PREFIX, default_model)`; each prefix
    is tried as `{PREFIX}_BASE_URL` / `{PREFIX}_API_KEY` / `{PREFIX}_MODEL`.
    """
    for prefix, default_model in prefixes:
        base = (os.getenv(f"{prefix}_BASE_URL") or "").strip()
        key = (os.getenv(f"{prefix}_API_KEY") or "").strip()
        if base and key:
            model = (os.getenv(f"{prefix}_MODEL") or default_model).strip()
            if model:
                return GatewayConfig(base.rstrip("/"), key, model)
    return None


def call_chat(
    gw: GatewayConfig,
    *,
    system: str,
    user: str,
    max_tokens: int = 1024,
    temperature: float = 0,
    timeout: int = 20,
    protocol_env: str = "ROUTER_PROTOCOL",
) -> str:
    """POST one chat completion; return the assistant's text content.

    Tries OpenAI-compatible `/chat/completions` first, then retries as an
    Anthropic-native `/v1/messages` call if the first attempt 404s — some
    gateway routes (Bedrock-backed ones on our gateway) only speak the latter.
    Set `{protocol_env}=anthropic` to skip straight to that dialect.
    """
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    protocol = (os.getenv(protocol_env) or "auto").strip().lower()
    if protocol == "anthropic":
        return _call_anthropic(gw, messages, max_tokens, temperature, timeout)
    try:
        return _call_openai(gw, messages, max_tokens, temperature, timeout)
    except NotOpenAICompatible:
        logger.info("%s is not OpenAI-compatible — retrying Anthropic /v1/messages", gw.base_url)
        return _call_anthropic(gw, messages, max_tokens, temperature, timeout)


def _call_openai(gw: GatewayConfig, messages: list[dict], max_tokens: int, temperature: float, timeout: int) -> str:
    import requests

    resp = requests.post(
        f"{gw.base_url}/chat/completions",
        headers={"Authorization": f"Bearer {gw.api_key}", "Content-Type": "application/json"},
        json={"model": gw.model, "messages": messages, "max_tokens": max_tokens, "temperature": temperature},
        timeout=timeout,
    )
    if resp.status_code == 404:
        raise NotOpenAICompatible(f"{gw.base_url}/chat/completions → 404")
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


def _call_anthropic(gw: GatewayConfig, messages: list[dict], max_tokens: int, temperature: float, timeout: int) -> str:
    """Anthropic Messages dialect: `system` is a top-level field, content is a list."""
    import requests

    system = next((m["content"] for m in messages if m["role"] == "system"), "")
    body = {
        "model": gw.model,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "system": system,
        "messages": [{"role": m["role"], "content": m["content"]} for m in messages if m["role"] != "system"],
    }
    # Avoid `/v1/v1/messages` when the configured base already carries the version.
    root = re.sub(r"/v1$", "", gw.base_url)
    resp = requests.post(
        f"{root}/v1/messages",
        headers={
            "Authorization": f"Bearer {gw.api_key}",
            "x-api-key": gw.api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        },
        json=body,
        timeout=timeout,
    )
    resp.raise_for_status()
    blocks = resp.json().get("content") or []
    return "".join(b.get("text", "") for b in blocks if isinstance(b, dict))


__all__ = ["GatewayConfig", "NotOpenAICompatible", "call_chat", "resolve_gateway"]
