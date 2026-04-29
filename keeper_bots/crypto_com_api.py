import os
import httpx
import hmac
import hashlib
import json
from datetime import datetime

class CryptoComTradeAPI:
    """Crypto.com Trade API client for placing and managing orders"""
    
    def __init__(self, api_key, api_secret, sandbox=False):
        self.api_key = api_key
        self.api_secret = api_secret
        self.sandbox = sandbox
        self.base_url = "https://uat-api.3ona.co/v2" if sandbox else "https://api.crypto.com/v2"
        self.client = httpx.AsyncClient()
    
    def _sign_request(self, method, endpoint, params=None):
        """Sign request with API key and secret"""
        nonce = str(int(datetime.utcnow().timestamp() * 1000))
        
        if params is None:
            params = {}
        
        params_str = json.dumps(params, separators=(',', ':'), sort_keys=True)
        message = f"{method}{endpoint}{params_str}{nonce}"
        
        signature = hmac.new(
            self.api_secret.encode('utf-8'),
            message.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        
        return signature, nonce
    
    async def place_order(self, instrument_id, side, type_, size, price=None, **kwargs):
        """Place an order on Crypto.com
        
        Args:
            instrument_id: Trading pair (e.g., 'BTC_USDT')
            side: 'BUY' or 'SELL'
            type_: 'LIMIT' or 'MARKET'
            size: Order size
            price: Price for limit orders
            **kwargs: Additional parameters
        
        Returns:
            Order response from API
        """
        endpoint = "/private/create-order"
        
        params = {
            "instrument_id": instrument_id,
            "side": side,
            "type": type_,
            "quantity": str(size)
        }
        
        if type_ == "LIMIT" and price:
            params["price"] = str(price)
        
        params.update(kwargs)
        
        signature, nonce = self._sign_request("POST", endpoint, params)
        
        headers = {
            "X-API-Key": self.api_key,
            "X-Signature": signature,
            "X-Nonce": nonce,
            "Content-Type": "application/json"
        }
        
        try:
            response = await self.client.post(
                f"{self.base_url}{endpoint}",
                json=params,
                headers=headers
            )
            result = response.json()
            
            if result.get("code") != "0":
                raise ValueError(f"Order placement failed: {result.get('msg')}")
            
            return result.get("data", {})
        except Exception as e:
            raise Exception(f"Failed to place order: {str(e)}")
    
    async def get_order(self, instrument_id, order_id):
        """Get order details from Crypto.com
        
        Args:
            instrument_id: Trading pair (e.g., 'BTC_USDT')
            order_id: Order ID
        
        Returns:
            Order details
        """
        endpoint = "/private/get-order-detail"
        
        params = {
            "instrument_id": instrument_id,
            "order_id": order_id
        }
        
        signature, nonce = self._sign_request("POST", endpoint, params)
        
        headers = {
            "X-API-Key": self.api_key,
            "X-Signature": signature,
            "X-Nonce": nonce,
            "Content-Type": "application/json"
        }
        
        try:
            response = await self.client.post(
                f"{self.base_url}{endpoint}",
                json=params,
                headers=headers
            )
            result = response.json()
            
            if result.get("code") != "0":
                raise ValueError(f"Failed to get order: {result.get('msg')}")
            
            return result.get("data", {})
        except Exception as e:
            raise Exception(f"Failed to get order: {str(e)}")
    
    async def close(self):
        """Close the HTTP client"""
        await self.client.aclose()


class CryptoComAccountAPI:
    """Crypto.com Account API client for managing balances"""
    
    def __init__(self, api_key, api_secret, sandbox=False):
        self.api_key = api_key
        self.api_secret = api_secret
        self.sandbox = sandbox
        self.base_url = "https://uat-api.3ona.co/v2" if sandbox else "https://api.crypto.com/v2"
        self.client = httpx.AsyncClient()
    
    def _sign_request(self, method, endpoint, params=None):
        """Sign request with API key and secret"""
        nonce = str(int(datetime.utcnow().timestamp() * 1000))
        
        if params is None:
            params = {}
        
        params_str = json.dumps(params, separators=(',', ':'), sort_keys=True)
        message = f"{method}{endpoint}{params_str}{nonce}"
        
        signature = hmac.new(
            self.api_secret.encode('utf-8'),
            message.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        
        return signature, nonce
    
    async def get_account_balance(self, currency=None):
        """Get account balance from Crypto.com
        
        Args:
            currency: Optional specific currency to query (e.g., 'XCH')
        
        Returns:
            Balance information
        """
        endpoint = "/private/get-account-summary"
        
        params = {}
        if currency:
            params["currency"] = currency
        
        signature, nonce = self._sign_request("POST", endpoint, params)
        
        headers = {
            "X-API-Key": self.api_key,
            "X-Signature": signature,
            "X-Nonce": nonce,
            "Content-Type": "application/json"
        }
        
        try:
            response = await self.client.post(
                f"{self.base_url}{endpoint}",
                json=params,
                headers=headers
            )
            result = response.json()
            
            if result.get("code") != "0":
                raise ValueError(f"Failed to get balance: {result.get('msg')}")
            
            return {
                "code": "0",
                "data": [{"details": [result.get("data", {})]}]
            }
        except Exception as e:
            raise Exception(f"Failed to get account balance: {str(e)}")
    
    async def close(self):
        """Close the HTTP client"""
        await self.client.aclose()
