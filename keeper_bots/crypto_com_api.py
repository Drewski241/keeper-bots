import httpx
import hmac
import hashlib
import time
import logging


class CryptoComBaseAPI:
    def __init__(self, api_key, api_secret, sandbox=False):
        # ✅ Remove accidental whitespace/newlines
        self.api_key = api_key.strip()
        self.api_secret = api_secret.strip()

        self.sandbox = sandbox

        # ✅ Correct Exchange API endpoint
        self.base_url = (
            "https://uat-api.3ona.co/exchange/v1/"
            if sandbox else
            "https://api.crypto.com/exchange/v1/"
        )

        limits = httpx.Limits(
            max_keepalive_connections=20,
            max_connections=100,
        )

        self.client = httpx.AsyncClient(
            timeout=10.0,
            limits=limits,
        )

        self.logger = logging.getLogger(
            self.__class__.__name__
        )

        # Monotonic request IDs / nonces
        self._last_nonce = 0

        # ✅ Helpful startup log
        self.logger.info(
            "Crypto.com environment: %s",
            "SANDBOX" if sandbox else "PRODUCTION",
        )

    # =====================================================
    # NONCE / REQUEST ID
    # =====================================================
    def _get_request_id(self):

        request_id = int(time.time() * 1000)

        # Guarantee strictly increasing values
        if request_id <= self._last_nonce:
            request_id = self._last_nonce + 1

        self._last_nonce = request_id

        return request_id

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
    nonce = self._get_nonce()

    if params is None:
        params = {}

    # Crypto.com requires flattened sorted params
    param_str = ""

    for key in sorted(params.keys()):
        param_str += key + str(params[key])

    sig_payload = (
        method
        + str(nonce)
        + self.api_key
        + param_str
        + str(nonce)
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

        request_payload = self._sign_request(
            method,
            params,
        )

        try:
            # ✅ Exchange API expects POST to root endpoint
            response = await self.client.post(
                self.base_url,
                json=request_payload,
            )

            response.raise_for_status()

            result = response.json()

            self.logger.debug(
                "Crypto.com response (%s): %s",
                method,
                result,
            )

            # API-level errors
            if result.get("code") != 0:
                raise ValueError(
                    f"Crypto.com API error: {result}"
                )

            return result.get("result", {})

        except httpx.HTTPStatusError as e:
            raise Exception(
                f"HTTP {e.response.status_code}: "
                f"{e.response.text}"
            )

        except httpx.TimeoutException:
            raise Exception(
                "Crypto.com request timed out"
            )

        except Exception:
            raise

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
            else str(self._get_request_id())
        )

        # Additional optional params
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
