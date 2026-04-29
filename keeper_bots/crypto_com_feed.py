import os
import asyncio
import aiofiles
from collections import deque
import math
import json
import yaml
import logging.config
from datetime import datetime, timedelta
import websockets

from keeper_bots.coinbase_feed import CoinbaseFeed

if os.path.exists("log_conf.yaml"):
    with open("log_conf.yaml", "r") as f:
        config = yaml.safe_load(f)
        logging.config.dictConfig(config)

log = logging.getLogger("crypto_com_feed")

# Crypto.com price feed
# Keeps track of the volume-weighted average price based on trades on Crypto.com
class CryptoComFeed:

    def __init__(self, sym, uquote, url,
            startup_window_length=900,
            window_length=3600,
            verbose=False
    ):
        self.sym = sym  # Format: "BTC_USDT"
        self.market_sym = sym.replace("_", "-")  # Format: "BTC-USDT" for display
        self.uquote = uquote
        self.startup_window_length = timedelta(seconds=startup_window_length)
        self.window_length = timedelta(seconds=window_length)
        self.starttime = datetime.utcfromtimestamp(0)  # Begin of Unix epoch
        self.feed = deque()  # List of [price, size] pairs
        self.price = float("NaN")
        self.size = 0
        self.verbose = verbose
        self.url = url
        self.ws = None
        self.coinbase_feed = CoinbaseFeed(self.bq()[1], uquote)

    async def __aenter__(self):
        log.info("Entering CryptoComFeed context, connecting to Crypto.com websocket and subscribing...")
        await self.start()  # Connect to WebSocket
        await self.subscribe()  # Subscribe to trades channel
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        log.info("Exiting CryptoComFeed context, unsubscribing and closing Crypto.com websocket connection...")
        try:
            await self.unsubscribe()
        except Exception as e:
            log.error("Error during unsubscribe: %s", str(e), extra={"exception": str(e)})
        finally:
            await self.stop()

    async def start(self):
        """Connect to Crypto.com websocket"""
        log.info("Connecting to Crypto.com websocket at %s", self.url)
        try:
            self.ws = await websockets.connect(self.url)
            log.info("Connected to Crypto.com websocket")
        except Exception as e:
            log.error("Failed to connect to Crypto.com websocket: %s", str(e))
            raise

    async def stop(self):
        """Disconnect from Crypto.com websocket"""
        if self.ws:
            try:
                await self.ws.close()
                log.info("Closed Crypto.com websocket connection")
            except Exception as e:
                log.error("Error closing websocket: %s", str(e))

    async def subscribe(self):
        """Subscribe to trades channel on Crypto.com"""
        subscribe_message = {
            "method": "subscribe",
            "params": {
                "channels": [f"trade.{self.sym}"]
            },
            "nonce": int(datetime.utcnow().timestamp() * 1000)
        }
        try:
            await self.ws.send(json.dumps(subscribe_message))
            log.info("Subscribed to trade channel for %s", self.sym)
            # Start listening for messages
            asyncio.create_task(self._listen())
        except Exception as e:
            log.error("Failed to subscribe: %s", str(e))
            raise

    async def unsubscribe(self):
        """Unsubscribe from trades channel"""
        unsubscribe_message = {
            "method": "unsubscribe",
            "params": {
                "channels": [f"trade.{self.sym}"]
            },
            "nonce": int(datetime.utcnow().timestamp() * 1000)
        }
        try:
            await self.ws.send(json.dumps(unsubscribe_message))
            log.info("Unsubscribed from trade channel for %s", self.sym)
        except Exception as e:
            log.error("Failed to unsubscribe: %s", str(e))

    async def _listen(self):
        """Listen for incoming messages from websocket"""
        try:
            async for message in self.ws:
                self.__call__(message)
        except Exception as e:
            log.error("Error listening to websocket: %s", str(e))

    def bq(self):
        """Split symbol into base and quote currencies"""
        return self.sym.split("_")

    def recalculate_on_append(self, append_trade):
        if math.isnan(self.price):
            self.price = append_trade[0]
            self.size = append_trade[1]
        else:
            new_size = self.size + append_trade[1]
            new_price = (self.price * self.size + append_trade[0] * append_trade[1]) / new_size
            self.price = new_price
            self.size = new_size

    def recalculate_on_pop(self):
        if len(self.feed) == 1:
            self.price = float("NaN")
            self.size = 0
        elif len(self.feed) == 2:
            self.price = self.feed[1][0]
            self.size = self.feed[1][1]
        elif len(self.feed) > 2:
            pop_trade = self.feed[0]
            new_size = self.size - pop_trade[1]
            new_price = (self.price * self.size - pop_trade[0] * pop_trade[1]) / new_size
            self.price = new_price
            self.size = new_size
        else:
            raise ValueError("Tried to call 'recalculate_on_pop' on empty feed")

    def __call__(self, msg):
        """Websocket callback function - Updates the price whenever a new trade is received"""
        try:
            message = json.loads(msg)
        except json.JSONDecodeError:
            log.error("Failed to parse message: %s", msg)
            return

        if "result" in message and message["result"]["channel"] == f"trade.{self.sym}":
            # Subscription confirmation
            self.starttime = datetime.utcnow()
            log.info("Subscribed to %s spot trades on Crypto.com", self.sym)
            log.info("  Price calculation window length")
            log.info("    on start-up: %ss", int(self.startup_window_length.total_seconds()))
            log.info("    post ramp-up: %ss", int(self.window_length.total_seconds()))
            log.info("  Start time (UTC): %s", self.starttime.strftime("%Y-%m-%d %H:%M:%S"))

        elif "error" in message:
            raise Exception(f"Callback returned an error: {message['error']}")

        elif "params" in message and message["params"]["channel"] == f"trade.{self.sym}":
            # Trade data
            if self.starttime > datetime.utcfromtimestamp(0):
                # Drop old trades outside the price calculation window
                if self.feed:
                    now = datetime.utcnow()
                    num_popped = 0
                    while self.feed and self.feed[0][2] < now - self.window_length:
                        self.recalculate_on_pop()
                        old_trade = self.feed.popleft()
                        num_popped += 1
                        if self.verbose:
                            log.info("Popped: %s", old_trade)
                        if not self.feed:
                            break

                    if num_popped > 0:
                        log.info("New price: %.4f   (volume: %s)", self.price, sum([d[1] for d in self.feed]))

                # Add new trades
                for trade in message["params"]["data"]:
                    okx_price = float(trade["p"])  # p = price
                    if self.bq()[1] != self.uquote:
                        price = okx_price * self.coinbase_feed.price
                    else:
                        price = okx_price

                    if self.verbose:
                        log.info("Prices:")
                        log.info("  %s %s (Crypto.com)", okx_price, self.market_sym)
                        if self.coinbase_feed.client is not None:
                            log.info("  %s %s (Coinbase)", self.coinbase_feed.price, self.coinbase_feed.sym)
                            log.info("  %s %s-%s (Crypto.com & Coinbase)", price, self.bq()[0], self.uquote)
                        log.info("")

                    new_trade = [price, float(trade["q"]), datetime.utcfromtimestamp(int(trade["t"]) / 1000)]
                    self.recalculate_on_append(new_trade)
                    self.feed.append(new_trade)
                    if self.verbose:
                        log.info("Appended: %s", new_trade)

                # Print new price
                if datetime.utcnow() - self.startup_window_length > self.starttime:
                    if datetime.utcnow() - self.window_length < self.starttime:
                        ramp_up = " [ramp-up]"
                    else:
                        ramp_up = ""
                    log.info("New price%s: %.4f   (volume: %s)", ramp_up, self.price, sum([d[1] for d in self.feed]))
                else:
                    if self.verbose:
                        log.info("  No price yet. Still in start-up window")
            else:
                log.info("Dropping trade(s) as feed data not initialized yet")

    async def get_price(self):
        log.info("Crypto.com price: %.4f", self.price)
        return self.price

    async def save_price(self, save_frequency):
        now = datetime.utcnow()
        if now > self.starttime + self.window_length and self.starttime > datetime.utcfromtimestamp(0):
            if self.verbose:
                log.info("Writing price to file")
            async with aiofiles.open("crypto_com_price.txt", "w") as f:
                await f.write(f'{now.strftime("%Y-%m-%d %H:%M:%S")}: \
                {str(self.price)} {self.sym} \
                (volume [{self.bq()[0]}]: {self.size})')
