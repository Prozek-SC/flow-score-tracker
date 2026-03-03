"""
TradeStation API Client
Handles OAuth2 authentication and data fetching
"""
import os
import time
import requests
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()


class TradeStationClient:
    BASE_URL = "https://api.tradestation.com/v3"
    AUTH_URL = "https://signin.tradestation.com/oauth/token"

    def __init__(self):
        self.client_id = os.getenv("TRADESTATION_CLIENT_ID")
        self.client_secret = os.getenv("TRADESTATION_CLIENT_SECRET")
        self.access_token = None
        self.token_expiry = 0

    def authenticate(self):
        """Get OAuth2 access token using client credentials flow"""
        payload = {
            "grant_type": "client_credentials",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "audience": "https://api.tradestation.com",
        }
        resp = requests.post(self.AUTH_URL, data=payload)
        resp.raise_for_status()
        data = resp.json()
        self.access_token = data["access_token"]
        self.token_expiry = time.time() + data.get("expires_in", 3600) - 60
        return self.access_token

    def _headers(self):
        if not self.access_token or time.time() > self.token_expiry:
            self.authenticate()
        return {"Authorization": f"Bearer {self.access_token}"}

    def get_bars(self, symbol, interval="Daily", bars_back=200):
        """Fetch OHLCV bars for a symbol"""
        url = f"{self.BASE_URL}/marketdata/barcharts/{symbol}"
        params = {
            "interval": interval,
            "barsback": bars_back,
            "unit": "Daily" if interval == "Daily" else "Minute",
        }
        resp = requests.get(url, headers=self._headers(), params=params)
        resp.raise_for_status()
        return resp.json().get("Bars", [])

    def get_quote(self, symbol):
        """Get real-time quote"""
        url = f"{self.BASE_URL}/marketdata/quotes/{symbol}"
        resp = requests.get(url, headers=self._headers())
        resp.raise_for_status()
        quotes = resp.json().get("Quotes", [])
        return quotes[0] if quotes else None

    def get_option_chain(self, symbol, expiration_date=None):
        """Fetch options chain for unusual flow analysis"""
        url = f"{self.BASE_URL}/marketdata/options/chains/{symbol}"
        params = {"strikeProximity": 10}
        if expiration_date:
            params["expiration"] = expiration_date
        resp = requests.get(url, headers=self._headers(), params=params)
        resp.raise_for_status()
        return resp.json()
