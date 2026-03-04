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


class TradierOptionsClient:
    """
    Tradier free brokerage API — options chain data.
    Sign up free at tradier.com/individual/api
    Uses the sandbox for testing, production for live data.
    """
    PROD_URL  = "https://api.tradier.com/v1"
    SB_URL    = "https://sandbox.tradier.com/v1"

    def __init__(self):
        self.api_key = os.getenv("TRADIER_API_KEY", "")
        self.base    = self.PROD_URL if self.api_key else self.SB_URL
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
        })

    def get_flow_for_ticker(self, symbol: str) -> dict:
        """
        Derive options flow signals from the options chain.
        Focuses on near-term expirations (7-45 DTE) where
        institutional positioning is most visible.
        """
        if not self.api_key:
            return self._empty_flow()

        # Step 1: get available expirations
        expirations = self._get_expirations(symbol)
        if not expirations:
            return self._empty_flow()

        # Focus on nearest 3 expirations (7-45 DTE sweet spot)
        target_exps = expirations[:3]

        all_calls, all_puts = [], []
        avg_volumes = []

        for exp in target_exps:
            chain = self._get_chain(symbol, exp)
            if not chain:
                continue
            calls = [c for c in chain if c.get("option_type") == "call"]
            puts  = [c for c in chain if c.get("option_type") == "put"]
            all_calls.extend(calls)
            all_puts.extend(puts)

            # Collect volume for spike detection
            vols = [c.get("volume", 0) or 0 for c in chain]
            avg_volumes.extend(vols)

        if not all_calls and not all_puts:
            return self._empty_flow()

        # Put/Call ratio by volume
        call_vol = sum(c.get("volume", 0) or 0 for c in all_calls)
        put_vol  = sum(c.get("volume", 0) or 0 for c in all_puts)
        pc_ratio = round(put_vol / call_vol, 2) if call_vol > 0 else 99.0

        # OI skew — is open interest concentrated in calls?
        call_oi = sum(c.get("open_interest", 0) or 0 for c in all_calls)
        put_oi  = sum(c.get("open_interest", 0) or 0 for c in all_puts)
        oi_skew = "calls" if call_oi > put_oi * 1.2 else "puts" if put_oi > call_oi * 1.2 else "neutral"

        # Volume spike — flag any single contract with outsized volume
        # (proxy for sweep/block activity)
        max_single_vol = max((c.get("volume", 0) or 0 for c in all_calls + all_puts), default=0)
        avg_vol = (sum(avg_volumes) / len(avg_volumes)) if avg_volumes else 1
        vol_spike = max_single_vol > avg_vol * 3

        # Volume ratio — total options vol vs average
        total_vol = call_vol + put_vol
        vol_ratio = round(total_vol / (avg_vol * len(avg_volumes) + 1), 2)

        return {
            "put_call_ratio": pc_ratio,
            "call_volume":    call_vol,
            "put_volume":     put_vol,
            "call_oi":        call_oi,
            "put_oi":         put_oi,
            "oi_skew":        oi_skew,
            "vol_spike":      vol_spike,
            "vol_ratio":      vol_ratio,
            "sweep_count":    1 if vol_spike else 0,  # sweep proxy
            "bullish_flow":   pc_ratio < 0.7 and oi_skew != "puts",
        }

    def get_unusual_activity(self, symbol: str) -> dict:
        """
        Wrapper kept for API compatibility with pipeline.py.
        Tradier flow data is all in get_flow_for_ticker.
        """
        return {}

    def _get_expirations(self, symbol: str) -> list:
        try:
            url  = f"{self.base}/markets/options/expirations"
            resp = self.session.get(url, params={"symbol": symbol, "includeAllRoots": "true"})
            if resp.status_code != 200:
                return []
            data = resp.json()
            exps = data.get("expirations", {}).get("date", [])
            return exps if isinstance(exps, list) else [exps]
        except:
            return []

    def _get_chain(self, symbol: str, expiration: str) -> list:
        try:
            url  = f"{self.base}/markets/options/chains"
            resp = self.session.get(url, params={
                "symbol":     symbol,
                "expiration": expiration,
                "greeks":     "false",
            })
            if resp.status_code != 200:
                return []
            data    = resp.json()
            options = data.get("options", {}).get("option", [])
            return options if isinstance(options, list) else [options]
        except:
            return []

    def _empty_flow(self) -> dict:
        return {
            "put_call_ratio": 1.0,
            "call_volume":    0,
            "put_volume":     0,
            "call_oi":        0,
            "put_oi":         0,
            "oi_skew":        "neutral",
            "vol_spike":      False,
            "vol_ratio":      1.0,
            "sweep_count":    0,
            "bullish_flow":   False,
        }
