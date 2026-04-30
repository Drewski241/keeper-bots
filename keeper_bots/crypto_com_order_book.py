import json
import logging
from datetime import datetime
import asyncio
import websockets
from sortedcontainers import SortedDict


class CryptoComOrderBook:
    @staticmethod
    def _descending_key(x):
        return -x

    def __init__(self, sym, uquote, url, verbose=False, logger=None):
        self.sym = sym
        self.market_sym = sym.replace("_", "-")
        if len(self.sym.split("_")) != 2:
            raise ValueError("Symbol must be BASE_QUOTE format")

        self.uquote = uquote
        self.ws = None
        self.verbose = verbose
        self.book = {}
        self.url = "wss://stream.crypto.com/exchange/v1/market"
        self.initialized = False
        self._lock = asyncio.Lock()
        self.logger = logger or logging.getLogger(__name__)

    async def connect(self):
        self.logger.info(f"Connecting to Crypto.com websocket at {self.url}")
        self.ws = await websockets.connect(self.url)
        self.logger.info("Connected to Crypto.com websocket")
        asyncio.create_task(self._listen())

    async def subscribe(self):
        self.logger.info("Subscribing to Crypto.com order book")

        channel = f"book.{self.sym}.10"

        msg = {
            "id": 1,
            "method": "subscribe",
            "params": {
                "channels": [channel]
            }
        }

        self.logger.info(f"Subscribing to: {channel}")
        await self.ws.send(json.dumps(msg))

    async def _listen(self):
        try:
            async for message in self.ws:
                self.__call__(message)
        except Exception as e:
            self.logger.error(f"Websocket listen error: {e}")

    def __call__(self, message):
        try:
            data = json.loads(message)
        except json.JSONDecodeError:
            self.logger.error(f"Bad JSON: {message}")
            return

        # Debug logging (keep this)
        self.logger.info(f"RAW WS: {data}")

        if data.get("method") != "public/book":
            return

        params = data.get("params", {})
        channel = params.get("channel", "")

        if not channel.startswith(f"book.{self.sym}"):
            return

        book_data = params.get("data", [])
        if not book_data:
            return

        book = book_data[0]

        bids = book.get("bids", [])
        asks = book.get("asks", [])

        if not bids or not asks:
            return

        if "asks" not in self.book:
            self.book["asks"] = SortedDict()
        if "bids" not in self.book:
            self.book["bids"] = SortedDict(self._descending_key)

        # Replace entire book (simpler + safer)
        self.book["asks"].clear()
        self.book["bids"].clear()

        for price, size in asks:
            self.book["asks"][float(price)] = size

        for price, size in bids:
            self.book["bids"][float(price)] = size

        if not self.initialized:
            self.logger.info(
                f"Initialized book bid={bids[0][0]} ask={asks[0][0]}"
            )

        self.initialized = True

    def mid_price(self):
        if not self.initialized:
            return None

        if not self.book.get("asks") or not self.book.get("bids"):
            return None

        try:
            lowest_ask = next(iter(self.book["asks"]))
            highest_bid = next(iter(self.book["bids"]))
            return (lowest_ask + highest_bid) / 2
        except Exception:
            return None
