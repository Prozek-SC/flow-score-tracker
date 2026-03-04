"""
Alpha Vantage Price Data Client
Replaces TradeStation for Trend + Momentum pillar data.
Returns bars in TradeStation-compatible format {Close, TotalVolume, High, Low, Open}
"""
import os
import time
import requests
from datetime import datetime, date


class AlphaVantageClient:
    BASE_URL = "https://www.alphavantage.co/query"

    def __init__(self):
        self.api_key = os.getenv("ALPHA_VANTAGE_API_KEY", "")
        self._cache = {}  # in-memory cache to avoid re-fetching same ticker
        self._last_call = 0

    def _rate_limit(self):
        """Free tier: 5 calls/min. Wait if needed."""
        elapsed = time.time() - self._last_call
        if elapsed < 13:  # ~4.5 calls/min to be safe
            time.sleep(13 - elapsed)
        self._last_call = time.time()

    def get_bars(self, symbol: str, bars_back: int = 200) -> list:
        """
        Fetch daily bars. Returns list of dicts with keys:
        Close, Open, High, Low, TotalVolume, TimeStamp
        Sorted oldest → newest (same as TradeStation).
        """
        if symbol in self._cache:
            return self._cache[symbol][-bars_back:]

        self._rate_limit()

        params = {
            "function": "TIME_SERIES_DAILY",
            "symbol": symbol,
            "outputsize": "compact",
            "apikey": self.api_key,
        }

        try:
            resp = requests.get(self.BASE_URL, params=params, timeout=15)
            resp.raise_for_status()
            data = resp.json()

            ts = data.get("Time Series (Daily)", {})
            if not ts:
                print(f"    AlphaVantage no data for {symbol}: {data}")
                return []

            bars = []
            for date_str, values in sorted(ts.items()):  # oldest first
                bars.append({
                    "TimeStamp": date_str,
                    "Open":        float(values.get("1. open", 0)),
                    "High":        float(values.get("2. high", 0)),
                    "Low":         float(values.get("3. low", 0)),
                    "Close":       float(values.get("4. close", 0)),
                    "TotalVolume": float(values.get("5. volume", 0)),
                })

            self._cache[symbol] = bars
            return bars[-bars_back:]

        except Exception as e:
            print(f"    AlphaVantage error ({symbol}): {e}")
            return []

    def get_quote(self, symbol: str) -> dict:
        """Get latest quote. Returns dict with 'Last' key."""
        bars = self.get_bars(symbol, bars_back=1)
        if bars:
            return {"Last": bars[-1]["Close"]}
        return {}
