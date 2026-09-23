"""Configuration for the Twitch Scraper. Everything can be set with an
environment variable; the defaults work out of the box.

    PORT                    port the API listens on (default 8000)
    TWITCH_PROXY            proxy URL for every request, e.g. http://user:pass@host:port
                            (default: none — direct). Twitch's GraphQL API answered
                            every request from one IP in testing, so you very
                            likely don't need this.
    TWITCH_FALLBACK_PROXY   proxy URL used only after Twitch answers 403/429 on
                            your own IP, for TWITCH_BLOCK_COOLDOWN seconds
                            (default: none — keep retrying direct)

Everything else below is a plain constant with a working default — edit it
here if you need to.
"""
import os

PORT = int(os.environ.get("PORT", "8000"))

# Retry policy for transport errors and blocks (every request).
MAX_RETRIES = 3
RETRY_BACKOFF = 2          # seconds, multiplied by the attempt number

# Twitch's Android app client id: its GraphQL answers cursors, chat replay and
# the chatters list without the browser integrity token the web id needs.
TWITCH_CLIENT_ID = "kd1unb4b3q4t58fwlpcbzcbnm76a8fp"
TWITCH_BLOCK_COOLDOWN = 900


def twitch_proxy():
    return os.environ.get("TWITCH_PROXY") or None


def twitch_fallback_proxy():
    return os.environ.get("TWITCH_FALLBACK_PROXY") or None
