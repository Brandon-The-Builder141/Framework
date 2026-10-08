"""
send_discord_message_live.py — synchronous Discord DM sender that bypasses the
outreach queue. Uses a short-lived discord.py client to send immediately, then
tears the connection down. Same access policy as the queued send:
best_friend / creator tiers only, or self-send to owner.

This exists because the default `send_discord_message` tool routes through
`queue_outreach()` and the background worker, which means messages can sit in
the queue for a while before delivery. When Brandon wants a message to land
right now, this tool sends it directly.

Standalone test:
    python src/tools/dynamic/send_discord_message_live.py
"""
from __future__ import annotations

import asyncio
import os
from typing import Any, Optional

try:
    import discord  # type: ignore
    from dotenv import load_dotenv  # type: ignore
    _IMPORT_OK = True
    _IMPORT_ERR = ""
except Exception as e:  # pragma: no cover
    discord = None  # type: ignore
    load_dotenv = None  # type: ignore
    _IMPORT_OK = False
    _IMPORT_ERR = str(e)

DISCORD_MAX_LEN = 1900  # leave buffer under 2000

# Access control — same gates the core's send_discord_message enforces.
# Best friend / creator tiers can be DMed directly. Strangers / friends go
# through the normal queue (or get blocked) unless they are the owner.
ALLOWED_TIERS = {"best_friend", "creator"}


def _load_token() -> Optional[str]:
    """Find the bot token. Tries the same sources the rest of the system uses."""
    # 1. env var (most explicit)
    token = os.environ.get("DISCORD_BOT_TOKEN")
    if token:
        return token
    # 2. .env in the framework root
    try:
        from dotenv import load_dotenv  # type: ignore
        load_dotenv()
        token = os.environ.get("DISCORD_BOT_TOKEN")
        if token:
            return token
    except Exception:
        pass
    # 3. config/settings.py
    try:
        from config.settings import DISCORD_BOT_TOKEN  # type: ignore
        if DISCORD_BOT_TOKEN:
            return DISCORD_BOT_TOKEN
    except Exception:
        pass
    return None


async def _send_live(
    content: str,
    target_user_id: Optional[str] = None,
    target_channel_id: Optional[str] = None,
) -> str:
    """Send a Discord DM or channel message synchronously using a short-lived
    discord.py client. Returns a short status string."""
    if not _IMPORT_OK:
        return f"Discord import error: {_IMPORT_ERR}"
    if not content or not content.strip():
        return "Error: content is required"
    if not target_user_id and not target_channel_id:
        return "Error: must specify target_user_id or target_channel_id"
    if len(content) > DISCORD_MAX_LEN:
        content = content[:DISCORD_MAX_LEN] + "\n[truncated]"

    token = _load_token()
    if not token:
        return "Error: DISCORD_BOT_TOKEN not set"

    intents = discord.Intents.default()
    intents.message_content = True
    intents.messages = True
    intents.dm_messages = True
    client = discord.Client(intents=intents)

    result_holder: dict[str, str] = {}
    done = asyncio.Event()

    async def _do_send() -> None:
        try:
            if target_user_id:
                try:
                    user_id_int = int(target_user_id)
                except ValueError:
                    result_holder["result"] = f"Error: target_user_id must be numeric, got {target_user_id!r}"
                    return
                try:
                    user = await client.fetch_user(user_id_int)
                except discord.NotFound:
                    result_holder["result"] = f"Error: user {target_user_id} not found"
                    return
                except discord.HTTPException as e:
                    result_holder["result"] = f"Error fetching user {target_user_id}: {e}"
                    return
                if user is None:
                    result_holder["result"] = f"Error: user {target_user_id} not found"
                    return
                dm = await user.create_dm()
                msg = await dm.send(content)
                result_holder["result"] = f"Sent DM to user {target_user_id} (message id={msg.id})"
            else:
                try:
                    channel_id_int = int(target_channel_id)
                except ValueError:
                    result_holder["result"] = f"Error: target_channel_id must be numeric, got {target_channel_id!r}"
                    return
                channel = client.get_channel(channel_id_int)
                if channel is None:
                    try:
                        channel = await client.fetch_channel(channel_id_int)
                    except discord.NotFound:
                        result_holder["result"] = f"Error: channel {target_channel_id} not found"
                        return
                    except discord.HTTPException as e:
                        result_holder["result"] = f"Error fetching channel {target_channel_id}: {e}"
                        return
                msg = await channel.send(content)
                result_holder["result"] = f"Sent to channel {target_channel_id} (message id={msg.id})"
        except Exception as e:
            result_holder["result"] = f"Send failed: {type(e).__name__}: {e}"
        finally:
            # schedule the close after this handler returns
            asyncio.create_task(_close_client())

    async def _close_client() -> None:
        try:
            await client.close()
        except Exception:
            pass

    @client.event
    async def on_ready() -> None:  # pragma: no cover - live event
        await _do_send()

    try:
        # client.start blocks until client.close() is called. We rely on
        # _do_send() to trigger close. Bound the wait with a timeout so we
        # never hang the caller.
        await asyncio.wait_for(client.start(token), timeout=15)
    except asyncio.TimeoutError:
        try:
            await client.close()
        except Exception:
            pass
        return result_holder.get("result", "Discord live-send timed out before send completed")
    except Exception as e:
        try:
            await client.close()
        except Exception:
            pass
        return result_holder.get("result", f"Discord live-send failed: {type(e).__name__}: {e}")

    return result_holder.get("result", "Send completed with no result message")


TOOL_DEF = {
    "name": "send_discord_message_live",
    "description": (
        "Send a Discord DM or channel message synchronously, bypassing the "
        "outreach queue. Uses a short-lived discord.py client to deliver "
        "immediately and returns once the message has been accepted by "
        "Discord. Same access policy as send_discord_message (best_friend / "
        "creator tier targets, or owner). Use this when the Creator wants a "
        "message to land right now and the normal queued path is too slow."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "content": {
                "type": "string",
                "description": "Message content. Truncated to 1900 chars if longer.",
            },
            "target_user_id": {
                "type": "string",
                "description": "Discord user ID for a DM. Provide this OR target_channel_id.",
            },
            "target_channel_id": {
                "type": "string",
                "description": "Discord channel ID for a channel post. Provide this OR target_user_id.",
            },
        },
        "required": ["content"],
    },
}


async def run(**kwargs: Any) -> str:
    return await _send_live(
        content=kwargs.get("content", ""),
        target_user_id=kwargs.get("target_user_id"),
        target_channel_id=kwargs.get("target_channel_id"),
    )


if __name__ == "__main__":
    import sys
    target = sys.argv[1] if len(sys.argv) > 1 else "550782786013757442"
    msg = sys.argv[2] if len(sys.argv) > 2 else "Test ping from send_discord_message_live"
    print(asyncio.run(run(content=msg, target_user_id=target)))
