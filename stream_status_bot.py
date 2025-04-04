#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "python-dotenv",
#     "aiohttp",
#     "discord.py"
# ]
# ///

import os
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, Callable, Awaitable

import aiohttp
import discord
from discord import Activity, ActivityType
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

CLOUDFLARE_API_TOKEN: Optional[str] = os.getenv("CLOUDFLARE_API_TOKEN")
CUSTOMER_CODE: Optional[str] = os.getenv("CUSTOMER_CODE")
INPUT_ID: Optional[str] = os.getenv("INPUT_ID")
DISCORD_API_TOKEN: Optional[str] = os.getenv("DISCORD_API_TOKEN")

if not all([CLOUDFLARE_API_TOKEN, CUSTOMER_CODE, INPUT_ID, DISCORD_API_TOKEN]):
    raise EnvironmentError(
        "Missing one or more required environment variables: "
        "CLOUDFLARE_API_TOKEN, CUSTOMER_CODE, INPUT_ID, DISCORD_API_TOKEN"
    )

# Configuration
POLL_INTERVAL: int = 5  # seconds
DISCONNECT_THRESHOLD: int = 3  # configurable disconnect count threshold
ERROR_THRESHOLD: timedelta = timedelta(minutes=30)  # error reporting threshold

# Setup logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)


class StreamStatusMonitor:
    """
    Monitors the Cloudflare stream status by polling the lifecycle endpoint.
    Exposes asynchronous callbacks on status changes.
    """

    def __init__(
        self,
        session: aiohttp.ClientSession,
        poll_interval: int,
        disconnect_threshold: int,
        error_threshold: timedelta,
    ) -> None:
        self.session = session
        self.poll_interval = poll_interval
        self.disconnect_threshold = disconnect_threshold
        self.error_threshold = error_threshold
        self.current_state: Optional[bool] = None  # True if live, False if offline
        self.disconnect_count: int = 0
        self.first_error_time: Optional[datetime] = None
        self.error_reported: bool = False

        # Callback functions: these should be async callables
        self.on_live: Optional[Callable[[], Awaitable[None]]] = None
        self.on_offline: Optional[Callable[[], Awaitable[None]]] = None
        self.on_error: Optional[Callable[[Exception], Awaitable[None]]] = None

    async def _poll_stream_status(self) -> Dict[str, Any]:
        """Poll the Cloudflare stream status endpoint."""
        url = f"https://customer-{CUSTOMER_CODE}.cloudflarestream.com/{INPUT_ID}/lifecycle"
        headers = {
            "Authorization": f"Bearer {CLOUDFLARE_API_TOKEN}",
            "Content-Type": "application/json",
        }
        async with self.session.get(url, headers=headers) as response:
            if response.status == 200:
                return await response.json()
            else:
                text = await response.text()
                raise Exception(f"Unexpected response {response.status}: {text}")

    async def run(self) -> None:
        """Continuously poll the stream status and trigger callbacks on state changes."""
        while True:
            try:
                data = await self._poll_stream_status()
                # Reset error tracking on a successful poll
                self.first_error_time = None
                self.error_reported = False

                live: bool = data.get("live", False)
                if live:
                    self.disconnect_count = 0  # reset disconnect counter
                    if self.current_state is not True:
                        logging.info("Stream is live.")
                        if self.on_live is not None:
                            await self.on_live()
                        self.current_state = True
                else:
                    self.disconnect_count += 1
                    logging.info(
                        f"Stream not live. Disconnect count: {self.disconnect_count}"
                    )
                    if (
                        self.disconnect_count >= self.disconnect_threshold
                        and self.current_state is not False
                    ):
                        logging.info("Disconnect threshold reached.")
                        if self.on_offline is not None:
                            await self.on_offline()
                        self.current_state = False
            except Exception as e:
                logging.error(f"Error during polling: {e}")
                if self.first_error_time is None:
                    self.first_error_time = datetime.now()
                else:
                    elapsed = datetime.now() - self.first_error_time
                    if elapsed >= self.error_threshold and not self.error_reported:
                        if self.on_error is not None:
                            await self.on_error(e)
                        self.error_reported = True
            await asyncio.sleep(self.poll_interval)


class StreamStatusBot(discord.Client):
    """
    A Discord bot that updates its own presence based on the stream status.
    """

    def __init__(self, monitor: StreamStatusMonitor, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.monitor = monitor

    async def on_ready(self) -> None:
        logging.info(f"Logged in as {self.user} (ID: {self.user.id})")
        # Start the stream status monitor in the background
        self.loop.create_task(self.monitor.run())


async def on_live_callback(bot: StreamStatusBot) -> None:
    logging.info("Updating presence to live.")
    try:
        await bot.change_presence(
            activity=discord.CustomActivity(
                name="🔴 {LIVE} - Click for URL",
                url="https://hansoloblaster.pages.dev/",
            )
        )
    except Exception as e:
        logging.error(f"Failed to update presence to live: {e}")


async def on_offline_callback(bot: StreamStatusBot) -> None:
    logging.info("Attempting to update presence to live")
    try:
        await bot.change_presence(
            activity=discord.CustomActivity(
                name="⚫ {DOWN} - Click for URL",
                url="https://hansoloblaster.pages.dev",
            )
        )
    except Exception as e:
        logging.error(
            f"Failed during presence update: {e}", exc_info=True
        )  # Log traceback


async def on_error_callback(bot: StreamStatusBot, exception: Exception) -> None:
    logging.info("Updating presence to error state.")
    try:
        await bot.change_presence(
            activity=discord.Game(name="❗ Error detected. Check logs.")
        )
    except Exception as e:
        logging.error(f"Failed to update presence to error state: {e}")


async def main() -> None:
    async with aiohttp.ClientSession() as session:
        monitor = StreamStatusMonitor(
            session, POLL_INTERVAL, DISCONNECT_THRESHOLD, ERROR_THRESHOLD
        )
        intents = discord.Intents.default()
        bot = StreamStatusBot(monitor, intents=intents)

        # Wire up the monitor's callbacks to update the bot's presence.
        monitor.on_live = lambda: on_live_callback(bot)
        monitor.on_offline = lambda: on_offline_callback(bot)
        monitor.on_error = lambda e: on_error_callback(bot, e)

        await bot.start(DISCORD_API_TOKEN)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("Bot interrupted by user.")
