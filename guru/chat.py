"""Conversational Garth — OpenRouter + tools + memory."""
from __future__ import annotations

import json
from typing import Any

from guru.agent_tools import execute_tool, tool_definitions
from guru.conversation_memory import append_turn, load_history
from guru.env import OPENAI_API_KEY, OPENAI_BASE_URL, OPENAI_MODEL, OPENAI_MODELS
from guru.logger import log_action
from guru.persona import build_system_prompt

MAX_TOOL_ROUNDS = 6


def _openrouter_extra() -> dict | None:
    if OPENAI_BASE_URL and "openrouter" in OPENAI_BASE_URL.lower():
        return {"provider": {"ignore": ["Poolside"]}}
    return None


def _is_rate_limited(err: Exception) -> bool:
    s = str(err).lower()
    return "429" in s or "rate-limit" in s or "rate limit" in s or "temporarily rate" in s


async def _complete_with_fallback(client: Any, kw: dict[str, Any]) -> Any:
    """Try each model in OPENAI_MODELS in order (free-first).

    Falls through to the next model only on a rate-limit (429); any other error
    propagates immediately. ``kw`` must NOT contain ``model`` — it is supplied
    per attempt here.
    """
    last_err: Exception | None = None
    for model in OPENAI_MODELS:
        try:
            resp = await client.chat.completions.create(model=model, **kw)
            if model != OPENAI_MODELS[0]:
                log_action("garth_model_fallback", f"used fallback model {model}", level="info")
            return resp
        except Exception as e:  # noqa: BLE001 — try the next model on ANY failure
            last_err = e
            reason = "rate-limited" if _is_rate_limited(e) else str(e)[:80]
            log_action("garth_model_skip", f"{model} unavailable ({reason}), trying next", level="warn")
            continue
    raise last_err  # type: ignore[misc] — every model in the chain failed


async def chat_with_garth(
    user_text: str,
    *,
    ctx: Any,
    bot: Any,
    user_id: str,
    user_name: str,
) -> str:
    if not OPENAI_API_KEY:
        return (
            "I need an OpenRouter key to talk — add OPENROUTER_API_KEY or OPENAI_API_KEY "
            "to guru/.env (same key as Solen works)."
        )

    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL)
    system = build_system_prompt(user_id, user_name)
    messages: list[dict[str, Any]] = [{"role": "system", "content": system}]
    messages.extend(load_history(user_id))
    messages.append({"role": "user", "content": user_text})

    tools = tool_definitions()
    extra = _openrouter_extra()

    for _ in range(MAX_TOOL_ROUNDS):
        kw: dict[str, Any] = {
            "messages": messages,
            "tools": tools,
            "tool_choice": "auto",
            "max_tokens": 500,
            "temperature": 0.85,
        }
        if extra:
            kw["extra_body"] = extra

        try:
            resp = await _complete_with_fallback(client, kw)
        except Exception as e:
            log_action("garth_llm_error", str(e)[:200], level="error")
            return f"Something glitched on my end — try again in a sec. ({e})"

        if not getattr(resp, "choices", None):
            # HTTP 200 with an error body (OpenRouter free tier) -> choices=None.
            detail = getattr(resp, "error", None) or "no choices"
            log_action("garth_llm_error", f"empty completion: {detail}", level="error")
            return "Something glitched on my end — try again in a sec."

        msg = resp.choices[0].message
        if msg.tool_calls:
            messages.append(
                {
                    "role": "assistant",
                    "content": msg.content or None,
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments or "{}",
                            },
                        }
                        for tc in msg.tool_calls
                    ],
                }
            )
            seen_skip = False
            for tc in msg.tool_calls:
                try:
                    args = json.loads(tc.function.arguments or "{}")
                except json.JSONDecodeError:
                    args = {}
                if not isinstance(args, dict):
                    args = {}
                if tc.function.name == "skip_ambient_track":
                    if seen_skip:
                        result = "Already switching — give the new track a moment."
                        messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": tc.id,
                                "content": result,
                            }
                        )
                        continue
                    seen_skip = True
                result = await execute_tool(
                    tc.function.name,
                    args,
                    ctx=ctx,
                    bot=bot,
                    user_id=user_id,
                )
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": str(result)[:4000],
                    }
                )
            continue

        reply = (msg.content or "").strip() or "I'm here — what do you need?"
        try:
            append_turn(user_id, user_text, reply)
        except OSError as e:
            log_action("memory_save_error", str(e)[:120], level="warn")
        return reply

    return "I got tangled up — try asking again."
