import json
import logging
from datetime import datetime
from pprint import pprint
import asyncio
import websockets

from sortedcontainers import SortedDict


class CryptoComOrderBook:
    """Crypto.com order book class

    Maintains an in-memory order book for a trading pair from Crypto.com exchange.

    The order book is stored as a dict with 'asks' and 'bids' fields, each being
    a SortedDict mapping price levels (as float keys) to volumes (as strings).
    Using SortedDict ensures O(log n) insertion/deletion and O(1) access to
    best bid/ask, eliminating the need for repeated sorting.

    This class handles websocket connections, subscriptions, and real-time updates
    to maintain an accurate representation of the order book.

    Attributes:
        sym: Trading symbol (e.g., 'BTC_USDT')
        uquote: Quote currency unit
        url: Websocket URL for Crypto.com
        verbose: Enable verbose logging
        book: Dict containing 'asks' (sorted ascending) and 'bids' (sorted descending) order book data
        ws: Websocket connection instance
        initialized: Whether a snapshot has been received
    """

    # Class-level function for descending sort (used for bids)
    @staticmethod
    def _descending_key(x):
        """Key function for sorting bids in descending order."""
        return -x

    def __init__(self, sym, uquote, url, verbose=False, logger=None):
        """Initialize Crypto.com order book.

        Args:
            sym: Trading symbol in format 'BASE_QUOTE' (e.g., 'BTC_USDT')
            uquote: Quote currency unit
            url: Websocket URL for Crypto.com connection
            verbose: Enable verbose logging (default: False)
            logger: Logger instance to use. If None, creates a default logger (default: None)

        Raises:
            ValueError: If symbol format is invalid
        """
        self.sym = sym  # Crypto.com format: BTC_USDT
        self.market_sym = sym.replace("_", "-")  # Display format: BTC-USDT
        bq = self.bq()
        if len(bq) != 2:
            raise ValueError("Symbol not valid. Must be of form <base>_<quote>")
        self.uquote = uquote
        self.ws = None
        self.verbose = verbose
        self.book = {}
        self.url = url
        self.initialized = False
        self._lock = asyncio.Lock()
        self.logger = logger or logging.getLogger(__name__)

    def bq(self):
        """Split symbol into base and quote currencies.

        Returns:
            List of [base, quote] currency strings
        """
        return self.sym.split("_")

    async def connect(self):
        """Connect to Crypto.com websocket.

        Establishes connection to the Crypto.com public websocket endpoint.
        """
        self.logger.info(f"Connecting to Crypto.com websocket at {self.url}")
        try:
            self.ws = await websockets.connect(self.url)
            self.logger.info("Connected to Crypto.com websocket")
            # Start listening for messages
            asyncio.create_task(self._listen())
        except Exception as e:
            self.logger.error(f"Failed to connect: {e}")
            raise

    async def subscribe(self):
        """Subscribe to order book websocket channel.

        Subscribes to the order book channel for the configured trading symbol.
        """
        self.logger.info("Subscribing to Crypto.com order book")
        subscribe_message = {
            "method": "subscribe",
            "params": {
                "channels": [f"book.{self.sym}.25"]
            },
            "nonce": int(datetime.utcnow().timestamp() * 1000)
        }
        try:
            await self.ws.send(json.dumps(subscribe_message))
            self.logger.info("Subscribed to Crypto.com order book")
        except Exception as e:
            self.logger.error(f"Failed to subscribe: {e}")
            raise

    async def _listen(self):
        """Listen for incoming messages from websocket"""
        try:
            async for message in self.ws:
                self.__call__(message)
        except Exception as e:
            self.logger.error(f"Error listening to websocket: {e}")

    def print(self):
        """Print the current order book to console in a clean format."""
        print("Order book:")
        # Convert to list of tuples for clean printing with proper ordering
        asks_list = list(self.book.get("asks", {}).items())
        asks_list.sort(key=lambda x: x[0], reverse=True)

        bids_list = list(self.book.get("bids", {}).items())
        bids_list.sort(key=lambda x: x[0], reverse=True)

        clean_book = {"asks": asks_list, "bids": bids_list}
        pprint(clean_book)

    def __call__(self, message):
        """Handle incoming websocket messages.

        Processes subscription confirmations, snapshots, and updates from Crypto.com.
        Updates the internal order book representation accordingly.

        Args:
            message: JSON string message from Crypto.com websocket

        Raises:
            ValueError: If an unknown event is received
            Exception: If an error is returned or unknown action is received

        Reference:
            https://exchange-docs.crypto.com/exchange-user-guide/websocket/user-private-channels
        """
        try:
            message = json.loads(message)
        except json.JSONDecodeError:
            self.logger.error(f"Failed to parse message: {message}")
            return

        if "result" in message and message["result"]["channel"] == f"book.{self.sym}.25":
            # Subscription confirmation
            self.starttime = datetime.utcnow()
            self.logger.info(f"Subscribed to {self.sym} order book on Crypto.com")
            self.logger.info(
                f"  Start time (UTC): {self.starttime.strftime('%Y-%m-%d %H:%M:%S')}"
            )

        elif "error" in message:
            raise Exception(f"Callback returned an error: {message['error']}")

        elif "params" in message and message["params"]["channel"] == f"book.{self.sym}.25":
            data = message["params"]["data"]
            
            if "snapshot" in data:
                # Order book snapshot
                self.logger.info("ORDER BOOK SNAPSHOT received")
                snapshot = data["snapshot"]

                # Asks sorted ascending (lowest first)
                self.book["asks"] = SortedDict()
                for price_str, size_str in snapshot[0].items():
                    price_float = float(price_str)
                    self.book["asks"][price_float] = size_str

                # Bids sorted descending (highest first)
                self.book["bids"] = SortedDict(self._descending_key)
                for price_str, size_str in snapshot[1].items():
                    price_float = float(price_str)
                    self.book["bids"][price_float] = size_str

                self.initialized = True

            elif "update" in data:
                # Order book update
                if self.verbose:
                    self.logger.debug(f"ORDER BOOK UPDATE received: {data['update']}")

                update = data["update"]
                
                # Process asks updates
                if len(update) > 0:
                    for price_str, size_str in update[0].items():
                        if "asks" not in self.book:
                            self.book["asks"] = SortedDict()
                        
                        price_float = float(price_str)
                        if float(size_str) > 0:
                            self.book["asks"][price_float] = size_str
                        else:
                            self.book["asks"].pop(price_float, None)

                # Process bids updates
                if len(update) > 1:
                    if "bids" not in self.book:
                        self.book["bids"] = SortedDict(self._descending_key)
                    
                    for price_str, size_str in update[1].items():
                        price_float = float(price_str)
                        if float(size_str) > 0:
                            self.book["bids"][price_float] = size_str
                        else:
                            self.book["bids"].pop(price_float, None)

    def mid_price(self) -> float:
        """Calculate the mid price of the order book.

        The mid price is the average of the lowest ask and highest bid.
        With SortedDict, this is an O(1) operation accessing the first elements.

        Returns:
            Mid price as float, or None if order book is not initialized
            or is empty
        """
        if not self.initialized:
            return None

        if not self.book or "asks" not in self.book or "bids" not in self.book:
            return None

        if not self.book["asks"] or not self.book["bids"]:
            return None

        try:
            # O(1) access to best prices with SortedDict
            lowest_ask = self.book["asks"].keys()[0]
            highest_bid = self.book["bids"].keys()[0]
            return (lowest_ask + highest_bid) / 2
        except (ValueError, KeyError, IndexError):
            return None

    def price(
        self, direction: str, amount: float, bq_toggle: bool
    ) -> tuple[float, float, float]:
        """Calculate price at which an amount of currency can be bought or sold.

        Returns average and max/min price at which amount will get bought/sold
        and corresponding amount.

        If order book isn't deep enough to cover requested amount, prices and
        amount returned reflect all liquidity in order book being used up.

        Note: size and amount values are in currency given by bq_toggle.
        volume is always in base currency.

        Args:
            direction: "buy" or "sell"
            amount: Amount to buy or sell
            bq_toggle: Whether amount is measured in base (True) or quote (False) currency

        Returns:
            Tuple of (price, level, size) where:
                - price: Average price at which amount will be bought or sold
                - level: Max/min price at which amount will be bought/sold
                - size: Amount that will be bought or sold (in currency given by bq_toggle)
            Returns (None, None, None) if order book is not ready

        Raises:
            ValueError: If direction is not 'buy' or 'sell'
        """
        if not self.initialized:
            return None, None, None

        if not self.book or "asks" not in self.book or "bids" not in self.book:
            return None, None, None

        def volume_to_size(volume, price, bq_toggle):
            """Return amount of base or quote currency equivalent to given base currency volume."""
            return volume if bq_toggle else price * volume

        def size_to_volume(size, price, bq_toggle):
            """Return amount of base currency equivalent to given size."""
            return size if bq_toggle else size / price

        if direction == "buy":
            side = "asks"
        elif direction == "sell":
            side = "bids"
        else:
            raise ValueError(
                f"Unknown direction '{direction}'. Must be 'buy' or 'sell'"
            )

        if not self.book.get(side):
            return None, None, None

        size = 0
        price = None
        level = None

        for price_key, v in self.book[side].items():
            level = price_key
            volume = min(
                float(v), size_to_volume(amount - size, level, bq_toggle)
            )

            if price is None:
                price = level
                size = volume_to_size(volume, level, bq_toggle)
            else:
                price = (
                    price * size_to_volume(size, price, bq_toggle) + level * volume
                ) / (size_to_volume(size, price, bq_toggle) + volume)
                size += volume_to_size(volume, level, bq_toggle)

            if size >= amount:
                break

        return price, level, size
