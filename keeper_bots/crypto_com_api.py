import httpx
import hmac
import hashlib
import json
import time
import os
import logging


class CryptoComBaseAPI:
    def __init__(self, api_key, api_secret, sandbox=False):
        self.api_key = api_key
        self.api_secret = api_secret
        self.sandbox = sandbox
        self.base_url = (
            "https://uat-api.3ona.co/v2/"
            if sandbox else
            "https://api.crypto.com/v2/"
        )
        self.client = httpx.AsyncClient(timeout=10.0)
        self.logger = logging.getLogger(self.__class__.__name__)
        self._nonce_counter = 0

    def _get_nonce(self):
        # Prevent collisions even within same ms
        self._nonce_counter += 1
        return int(time.time() * 1000) * 1000 + self._nonce_counter

    def _sign_request(self, method, params=None):
        nonce = self._get_nonce()

        if params is None:
            params = {}

        # ✅ canonical serialization (CRITICAL FIX)
        param_str = json.dumps(params, separators=(",", ":"), sort_keys=True)

        sig_payload = f"{method}{nonce}{self.api_key}{param_str}{nonce}"

        signature = hmac.new(
            self.api_secret.encode(),
            sig_payload.encode(),
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
        request = self._sign_request(method, params)

        try:
            response = await self.client.post(self.base_url, json=request)
            response.raise_for_status()
            result = response.json()

            if result.get("code") != 0:
                raise ValueError(f"API error: {result}")

            return result.get("result", {})

        except httpx.HTTPStatusError as e:
            raise Exception(f"HTTP error: {e.response.text}")
        except Exception:
            raise

    async def close(self):
        await self.client.aclose()


# =========================
# TRADE API
# =========================
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
                raise ValueError("LIMIT order requires price")
            params["price"] = str(price)

        # ✅ client order id (VERY useful for tracking)
        if client_oid:
            params["client_oid"] = client_oid
        else:
            params["client_oid"] = str(self._get_nonce())

        params.update(kwargs)

        result = await self._post(method, params)
        self.logger.info(f"Order placed: {result}")
        return result

    async def get_order(self, instrument_id, order_id):
        method = "private/get-order-detail"

        params = {
            "instrument_name": instrument_id,
            "order_id": order_id,
        }

        result = await self._post(method, params)
        return result


# =========================
# ACCOUNT API
# =========================
class CryptoComAccountAPI(CryptoComBaseAPI):
    async def get_account_balance(self, currency=None):
        method = "private/get-account-summary"

        params = {}
        if currency:
            params["currency"] = currency

        result = await self._post(method, params)

        accounts = result.get("accounts", [])

        if currency:
            return next(
                (acc for acc in accounts if acc["currency"] == currency),
                None,
            )

        return accounts
