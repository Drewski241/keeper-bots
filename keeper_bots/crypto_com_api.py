import httpx
import hmac
import hashlib
import json
import time
import logging


class CryptoComBaseAPI:
    def __init__(self, api_key, api_secret, sandbox=False):
        self.api_key = api_key
        self.api_secret = api_secret
        self.sandbox = sandbox

        # ✅ Correct Exchange REST API endpoints
        self.base_url = (
            "https://uat-api.3ona.co/exchange/v1/"
            if sandbox else
            "https://api.crypto.com/exchange/v1/"
        )

        # ✅ Better connection handling
        limits = httpx.Limits(
            max_keepalive_connections=20,
            max_connections=100,
        )

        self.client = httpx.AsyncClient(
            timeout=10.0,
            limits=limits,
        )

        self.logger = logging.getLogger(self.__class__.__name__)

        # Prevent nonce collisions
        self._nonce_counter = 0

    def _get_nonce(self):
        self._nonce_counter += 1

        # millisecond timestamp + increment
        return int(time.time() * 1000) * 1000 + self._nonce_counter

    def _sign_request(self, method, params=None):
        nonce = self._get_nonce()

        if params is None:
            params = {}

        # ✅ Canonical param serialization
        param_str = json.dumps(
            params,
            separators=(",", ":"),
            sort_keys=True,
        )

        sig_payload = (
            f"{method}"
            f"{nonce}"
            f"{self.api_key}"
            f"{param_str}"
            f"{nonce}"
        )

        signature = hmac.new(
            self.api_secret.encode("utf-8"),
            sig_payload.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        return {
            "id": nonce,
            "method": method,
            "api_key": self.api_key,
            "params": params,
            "nonce": nonce,
            "sig": signature,
        }

    async def _post(self, method, params=None):
        request_payload = self._sign_request(method, params)

        # ✅ Correct endpoint routing
        url = f"{self.base_url}{method}"

        try:
            response = await self.client.post(
                url,
                json=request_payload,
            )

            response.raise_for_status()

            result = response.json()

            # Helpful debug logging
            self.logger.debug(
                "API response for %s: %s",
                method,
                result,
            )

            # Crypto.com API-level errors
            if result.get("code") != 0:
                raise ValueError(
                    f"Crypto.com API error: {result}"
                )

            return result.get("result", {})

        except httpx.HTTPStatusError as e:
            raise Exception(
                f"HTTP {e.response.status_code}: {e.response.text}"
            )

        except httpx.TimeoutException:
            raise Exception("Request timed out")

        except Exception:
            raise

    async def close(self):
        await self.client.aclose()


# ==========================================
# TRADE API
# ==========================================
class CryptoComTradeAPI(CryptoComBaseAPI):

    async def place_order(
        self,
        instrument_id,
        side,
        type_,
        size,
        price=None,
        client_oid=None,
        **kwargs,
    ):
        method = "private/create-order"

        order_type = type_.upper()

        params = {
            "instrument_name": instrument_id,
            "side": side.upper(),
            "type": order_type,
            "quantity": str(size),
        }

        # LIMIT order validation
        if order_type == "LIMIT":
            if price is None:
                raise ValueError(
                    "LIMIT order requires price"
                )

            params["price"] = str(price)

        # Strongly recommended by exchanges
        params["client_oid"] = (
            client_oid
            if client_oid
            else str(self._get_nonce())
        )

        # Additional optional params
        params.update(kwargs)

        result = await self._post(method, params)

        self.logger.info(
            "Order placed successfully: %s",
            result.get("order_id"),
        )

        return result

    async def get_order(
        self,
        instrument_id,
        order_id,
    ):
        method = "private/get-order-detail"

        params = {
            "instrument_name": instrument_id,
            "order_id": order_id,
        }

        return await self._post(method, params)

    async def cancel_order(
        self,
        instrument_id,
        order_id,
    ):
        method = "private/cancel-order"

        params = {
            "instrument_name": instrument_id,
            "order_id": order_id,
        }

        return await self._post(method, params)


# ==========================================
# ACCOUNT API
# ==========================================
class CryptoComAccountAPI(CryptoComBaseAPI):

    async def get_account_balance(
        self,
        currency=None,
    ):
        method = "private/get-account-summary"

        params = {}

        if currency:
            params["currency"] = currency

        result = await self._post(method, params)

        accounts = result.get("accounts", [])

        if currency:
            return next(
                (
                    acc for acc in accounts
                    if acc["currency"] == currency
                ),
                None,
            )

        return accounts
