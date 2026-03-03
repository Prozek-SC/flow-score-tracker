"""
Finviz Elite + Unusual Whales Data Clients
"""
import os
import requests
import pandas as pd
from io import StringIO
from dotenv import load_dotenv

load_dotenv()


class FinvizClient:
    """
    Finviz Elite screener export client.
    Uses the authenticated export endpoint to pull fundamentals,
    institutional ownership, short interest, and RS data.
    """
    EXPORT_URL = "https://elite.finviz.com/export.ashx"
    SCREENER_URL = "https://elite.finviz.com/screener.ashx"

    def __init__(self):
        self.email = os.getenv("FINVIZ_EMAIL")
        self.password = os.getenv("FINVIZ_PASSWORD")
        self.session = requests.Session()
        self._logged_in = False

    def login(self):
        """Authenticate with Finviz Elite"""
        login_url = "https://finviz.com/login.ashx"
        payload = {
            "email": self.email,
            "password": self.password,
            "remember": "true",
        }
        resp = self.session.post(login_url, data=payload)
        resp.raise_for_status()
        self._logged_in = True

    def get_ticker_data(self, symbols: list) -> dict:
        """
        Fetch screener data for a list of symbols.
        Returns dict keyed by ticker with all Finviz columns.
        """
        if not self._logged_in:
            self.login()

        tickers_str = ",".join(symbols)
        params = {
            "v": "152",
            "t": tickers_str,
            "o": "ticker",
        }
        resp = self.session.get(self.EXPORT_URL, params=params)
        resp.raise_for_status()

        df = pd.read_csv(StringIO(resp.text))
        result = {}
        for _, row in df.iterrows():
            ticker = row.get("Ticker", "")
            if ticker:
                result[ticker] = {
                    "institutional_own_pct": self._parse_pct(row.get("Inst Own", "0%")),
                    "institutional_trans_pct": self._parse_pct(row.get("Inst Trans", "0%")),
                    "short_float_pct": self._parse_pct(row.get("Short Float", "0%")),
                    "short_ratio": self._parse_float(row.get("Short Ratio", 0)),
                    "rs_rating": self._parse_float(row.get("Perf Year", "0%")),
                    "perf_week": self._parse_pct(row.get("Perf Week", "0%")),
                    "perf_month": self._parse_pct(row.get("Perf Month", "0%")),
                    "perf_quarter": self._parse_pct(row.get("Perf Quarter", "0%")),
                    "price": self._parse_float(row.get("Price", 0)),
                    "sma50": self._parse_float(row.get("SMA50", 0)),
                    "sma200": self._parse_float(row.get("SMA200", 0)),
                    "volume": self._parse_float(row.get("Volume", 0)),
                    "avg_volume": self._parse_float(row.get("Avg Volume", 0)),
                    "relative_volume": self._parse_float(row.get("Rel Volume", 0)),
                }
        return result

    def _parse_pct(self, val):
        try:
            return float(str(val).replace("%", "").strip())
        except:
            return 0.0

    def _parse_float(self, val):
        try:
            return float(str(val).replace(",", "").replace("%", "").strip())
        except:
            return 0.0


class UnusualWhalesClient:
    """
    Unusual Whales API client for options flow data.
    Docs: https://unusualwhales.com/api
    """
    BASE_URL = "https://api.unusualwhales.com/api"

    def __init__(self):
        self.api_key = os.getenv("UNUSUAL_WHALES_API_KEY")
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        })

    def get_flow_for_ticker(self, symbol: str) -> dict:
        """
        Fetch recent options flow for a ticker.
        Returns aggregated call/put sentiment.
        """
        url = f"{self.BASE_URL}/stock/{symbol}/flow-alerts"
        resp = self.session.get(url, params={"limit": 50})
        if resp.status_code != 200:
            return self._empty_flow()

        data = resp.json().get("data", [])
        return self._aggregate_flow(data)

    def get_unusual_activity(self, symbol: str) -> dict:
        """Check for unusual options activity flags"""
        url = f"{self.BASE_URL}/stock/{symbol}/option-contracts/unusual"
        resp = self.session.get(url)
        if resp.status_code != 200:
            return {"unusual": False, "sweep_count": 0}

        data = resp.json().get("data", [])
        sweeps = [d for d in data if d.get("is_sweep", False)]
        return {
            "unusual": len(data) > 0,
            "sweep_count": len(sweeps),
            "total_unusual": len(data),
        }

    def _aggregate_flow(self, flow_data: list) -> dict:
        if not flow_data:
            return self._empty_flow()

        calls = [f for f in flow_data if f.get("put_call", "").upper() == "CALL"]
        puts = [f for f in flow_data if f.get("put_call", "").upper() == "PUT"]
        call_premium = sum(f.get("premium", 0) for f in calls)
        put_premium = sum(f.get("premium", 0) for f in puts)
        total = call_premium + put_premium

        return {
            "call_premium": call_premium,
            "put_premium": put_premium,
            "put_call_ratio": round(put_premium / call_premium, 2) if call_premium > 0 else 99,
            "call_pct": round(call_premium / total * 100, 1) if total > 0 else 0,
            "bullish_flow": call_premium > put_premium,
            "total_flow_count": len(flow_data),
        }

    def _empty_flow(self):
        return {
            "call_premium": 0,
            "put_premium": 0,
            "put_call_ratio": 1.0,
            "call_pct": 50,
            "bullish_flow": False,
            "total_flow_count": 0,
        }
