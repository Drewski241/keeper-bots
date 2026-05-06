import httpx
import hmac
import hashlib
from datetime import datetime
import logging


class CryptoComTradeAPI:
    def __init__(self, api_key, api_secret, sandbox=False):
        self.api_key = api_key
        self.api_secret = api_secret
        self.sandbox = sandbox
        self.base_url = (
            "https://uat-api.3ona.co/v2/"
            if sandbox else
            "https://api.crypto.com/v2/"
        )
        self.client = httpx.AsyncClient()
        self.logger = logging.getLogger(__name__)

    def _sign_request(self, method, params=None):
        nonce = int(datetime.utcnow().timestamp() * 1000)

        if params is None:
            params = {}

        param_str = ""
        if params:
            param_str = "".join(f"{k}{v}" for k, v in sorted(params.items()))

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

    async def place_order(self, instrument_id, side, type_, size, price=None, **kwargs):
        method = "private/create-order"

        params = {
            "instrument_name": instrument_id,
            "side": side.upper(),
            "type": type_.upper(),
            "quantity": str(size),
        }

        if type_.upper() == "LIMIT" and price:
            params["price"] = str(price)

        params.update(kwargs)

        request = self._sign_request(method, params)

        try:
            response = await self.client.post(self.base_url, json=request)
            response.raise_for_status()
            result = response.json()

            self.logger.info(f"ORDER RESPONSE: {result}")

            if result.get("code") != 0:
                raise ValueError(f"Order placement failed: {result}")

            return result.get("result", {})

        except Exception as e:
            raise Exception(f"Failed to place order: {e}")

    async def get_order(self, instrument_id, order_id):
        method = "private/get-order-detail"

        params = {
            "instrument_name": instrument_id,
            "order_id": order_id,
        }

        request = self._sign_request(method, params)

        try:
            response = await self.client.post(self.base_url, json=request)
            response.raise_for_status()
            result = response.json()

            self.logger.info(f"GET ORDER RESPONSE: {result}")

            if result.get("code") != 0:
                raise ValueError(f"Failed to get order: {result}")

            return result.get("result", {})

        except Exception as e:
            raise Exception(f"Failed to get order: {e}")

    async def close(self):
        await self.client.aclose()


class CryptoComAccountAPI:
    def __init__(self, api_key, api_secret, sandbox=False, logger=None):
        self.api_key = api_key
        self.api_secret = api_secret
        self.sandbox = sandbox
        self.base_url = (
            "https://uat-api.3ona.co/v2/"
            if sandbox else
            "https://api.crypto.com/v2/"
        )
        self.client = httpx.AsyncClient()
        self.logger = logger or logging.getLogger(__name__)

    def _sign_request(self, method, params=None):
        nonce = int(datetime.utcnow().timestamp() * 1000)

        if params is None:
            params = {}

        param_str = ""
        if params:
            param_str = "".join(f"{k}{v}" for k, v in sorted(params.items()))

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

    async def get_account_balance(self, currency=None):
        method = "private/get-account-summary"

        params = {}
        if currency:
            params["currency"] = currency

        request = self._sign_request(method, params)

        try:
            response = await self.client.post(self.base_url, json=request)
            response.raise_for_status()
            result = response.json()

            # 🔍 keep this for debugging
            self.logger.info(f"BALANCE RESPONSE: {result}")

            if result.get("code") != 0:
                raise ValueError(f"API error: {result}")

            accounts = result.get("result", {}).get("accounts", [])

            if currency:
                for acc in accounts:
                    if acc["currency"] == currency:
                        return acc
                return None

            return accounts

        except Exception as e:
            raise Exception(f"Failed to get account balance: {e}")

    async def close(self):
        await self.client.aclose()
