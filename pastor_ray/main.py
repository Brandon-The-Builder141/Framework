"""Run with python -m pastor_ray.main. One instance per workspace."""
import logging
import logging.handlers
import socket
import argparse
import httpx
from dotenv import dotenv_values

from pastor_ray.settings import ROOT


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--play-on-start', action='store_true', help='Execute an explicitly owner-requested choir start after connecting')
    args = parser.parse_args()
    token = dotenv_values(ROOT / ".env").get("PASTOR_RAY_DISCORD_BOT_TOKEN")
    if not token:
        raise SystemExit("Missing PASTOR_RAY_DISCORD_BOT_TOKEN in pastor_ray/.env")
    instance = socket.socket()
    try:
        instance.bind(("127.0.0.1", 18763))
    except OSError:
        raise SystemExit("Pastor Ray is already running (local port 18763).") from None
    logs = ROOT / "logs"
    logs.mkdir(exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(logs / "ray.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    logging.basicConfig(level=logging.INFO, handlers=[handler, logging.StreamHandler()],
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    from pastor_ray.bot import Ray
    response = httpx.get("https://discord.com/api/v10/oauth2/applications/@me",
                        headers={"Authorization": "Bot " + token}, timeout=20)
    response.raise_for_status()
    flags = response.json().get("flags", 0)
    content_enabled = bool(flags & ((1 << 18) | (1 << 19)))
    if not content_enabled:
        logging.warning("Enable Message Content Intent in Discord Developer Portal for public server context. DMs and slash controls remain available.")
    bot = Ray(message_content=content_enabled, play_on_start=args.play_on_start)
    try:
        bot.run(token, log_handler=None)
    finally:
        instance.close()


if __name__ == "__main__":
    main()
