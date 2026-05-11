import httpx
import hmac
import hashlib
import time
import logging
import json


class CryptoComBaseAPI:
    def __init__(self, api_key, api_secret, sandbox=False):
        self.api_key = api_key
        self.api_secret = api_secret
        self.sandbox = sandbox

        self.base_url = (
            "https://uat-api.3ona.co/exchange/v1/"
            if sandbox
            else "https://api.crypto.com/exchange/v1/"
        )

        self.client = httpx.AsyncClient(timeout=10.0)
        self.logger = logging.getLogger(self.__class__.__name__)

        # nonce tracking
        self._last_nonce = 0

    # =====================================================
    # NONCE
    # =====================================================
    def _get_nonce(self):

        nonce = int(time.time() * 1000)

        # guarantee strictly increasing nonce
        if nonce <= self._last_nonce:
            nonce = self._last_nonce + 1

        self._last_nonce = nonce

        return nonce

    # =====================================================
    # PARAM SERIALIZATION
    # =====================================================
    def _params_to_str(self, obj):

        if obj is None:
            return ""

        if isinstance(obj, dict):
            return "".join(
                f"{key}{self._params_to_str(obj[key])}"
                for key in sorted(obj)
            )

        if isinstance(obj, list):
            return "".join(
                self._params_to_str(item)
                for item in obj
            )

        if isinstance(obj, bool):
            return str(obj).lower()

        return str(obj)

    # =====================================================
    # SIGN REQUEST
    # =====================================================
    def _sign_request(self, method, params=None):

        if params is None:
            params = {}

        nonce = self._get_nonce()

        param_str = self._params_to_str(params)

        sig_payload = (
            method
            + str(nonce)
            + self.api_key
            + param_str
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

    # =====================================================
    # POST REQUEST
    # =====================================================
    async def _post(self, method, params=None):

        payload = self._sign_request(
            method,
            params,
        )

        try:
            response = await self.client.post(
                self.base_url,
                json=payload,
            )

            response.raise_for_status()

            result = response.json()

            self.logger.debug(
                "Crypto.com response (%s): %s",
                method,
                json.dumps(result),
            )

            # API-level error
            if result.get("code") != 0:
                raise Exception(
                    f"Crypto.com API error: {result}"
                )

            return result.get("result", {})

        except httpx.HTTPStatusError as e:
            raise Exception(
                f"HTTP {e.response.status_code}: {e.response.text}"
            )

        except httpx.TimeoutException:
            raise Exception(
                "Crypto.com request timed out"
            )

    async def close(self):
        await self.client.aclose()


# =====================================================
# TRADE API
# =====================================================
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

        params = {
            "instrument_name": instrument_id,
            "side": side.upper(),
            "type": type_.upper(),
            "quantity": str(size),
        }

        if type_.upper() == "LIMIT":

            if price is None:
                raise ValueError(
                    "LIMIT order requires price"
                )

            params["price"] = str(price)

        params["client_oid"] = (
            client_oid
            if client_oid
            else str(self._get_nonce())
        )

        params.update(kwargs)

        result = await self._post(
            method,
            params,
        )

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

        return await self._post(
            method,
            params,
        )

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

        return await self._post(
            method,
            params,
        )


# =====================================================
# ACCOUNT API
# =====================================================
class CryptoComAccountAPI(CryptoComBaseAPI):

    async def get_account_balance(
        self,
        currency=None,
    ):

        method = "private/get-account-summary"

        params = {}

        if currency:
            params["currency"] = currency

        result = await self._post(
            method,
            params,
        )

        accounts = result.get(
            "accounts",
            [],
        )

        if currency:
            return next(
                (
                    acc for acc in accounts
                    if acc["currency"] == currency
                ),
                None,
            )

        return accounts
