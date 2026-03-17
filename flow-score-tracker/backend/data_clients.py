# Last updated: 2026-03-17 23:55 ET
"""
Data Clients — Finviz Elite + Tradier Options
"""
import os
import requests
import pandas as pd
from io import StringIO
from dotenv import load_dotenv

load_dotenv()

FINVIZ_EXPORT_URL = "https://elite.finviz.com/export.ashx"


class FinvizClient:
    """
    Finviz Elite API client using token-based authentication.
    Pass auth token via FINVIZ_API_TOKEN env var.
    URL format: https://elite.finviz.com/export.ashx?v=111&t=AAPL,MSFT&auth=TOKEN
    """

    # Columns to request — maps Finviz column names to our internal keys
    COLUMNS = [
        "Ticker", "Company", "Sector", "Industry", "Country",
        "Market Cap", "Price", "Change", "Volume", "Avg Volume",
        "Rel Volume", "SMA20", "SMA50", "SMA200",
        "52W High", "52W Low", "RSI (14)",
        "Perf Week", "Perf Month", "Perf Quart", "Perf Half", "Perf Year",
        "Inst Own", "Inst Trans", "Short Float", "Short Ratio",
        "EPS (ttm)", "P/E", "Forward P/E", "Insider Own",
    ]

    def __init__(self):
        self.token = os.getenv("FINVIZ_API_TOKEN")
        if not self.token:
            print("  WARNING: FINVIZ_API_TOKEN not set")

    def get_ticker_data(self, symbols: list) -> dict:
        """
        Fetch screener data for a list of tickers.
        Uses two Finviz views merged together:
          v=111 (overview): price, market cap, volume, sector, rel vol
          v=170 (technical): SMA20/50/200, perf fields, RSI, 52W high/low
        Returns dict keyed by ticker with standardized fields.
        """
        if not self.token:
            print("  Finviz: no API token — skipping")
            return {}
        if not symbols:
            return {}

        tickers_str = ",".join(symbols)
        base_url = f"{FINVIZ_EXPORT_URL}?t={tickers_str}&auth={self.token}"

        result = {}

        # --- Request 1: v=111 overview (price, vol, sector, market cap) ---
        try:
            resp1 = requests.get(f"{base_url}&v=111", timeout=15)
            if resp1.status_code in (401, 403):
                print(f"  Finviz: {resp1.status_code} — check FINVIZ_API_TOKEN")
                return {}
            resp1.raise_for_status()
            df1 = pd.read_csv(StringIO(resp1.text))
            print(f"  Finviz v=111 columns: {list(df1.columns)}")
            for _, row in df1.iterrows():
                ticker = str(row.get("Ticker", "")).strip()
                if not ticker:
                    continue
                result[ticker] = {
                    "price":               self._float(row.get("Price", 0)),
                    "volume":              self._float(row.get("Volume", 0)),
                    "avg_volume":          self._float(row.get("Avg Volume", 0)),
                    "relative_volume":     self._float(row.get("Rel Volume", 0)),
                    "market_cap":          self._float(row.get("Market Cap", 0)),
                    "sector":              str(row.get("Sector", "")),
                    "industry":            str(row.get("Industry", "")),
                    "rsi":                 self._float(row.get("RSI (14)", row.get("RSI", 50))),
                    # defaults — will be overwritten by v=170
                    "sma20": 0, "sma50": 0, "sma200": 0,
                    "perf_week": 0, "perf_month": 0, "perf_quarter": 0,
                    "perf_half": 0, "perf_year": 0, "perf_ytd": 0,
                    "52w_high": 0, "52w_low": 0,
                    "institutional_own": 0, "institutional_trans": 0,
                    "institutional_trans_pct": 0, "short_float": 0,
                    "short_ratio": 0, "insider_own": 0,
                }
        except Exception as e:
            print(f"  Finviz v=111 error: {e}")
            return {}

        # --- Request 2: v=170 technical (SMA, perf, 52W) ---
        try:
            resp2 = requests.get(f"{base_url}&v=170", timeout=15)
            resp2.raise_for_status()
            df2 = pd.read_csv(StringIO(resp2.text))
            print(f"  Finviz v=170 columns: {list(df2.columns)}")
            for _, row in df2.iterrows():
                ticker = str(row.get("Ticker", "")).strip()
                if not ticker or ticker not in result:
                    continue
                result[ticker].update({
                    "sma20":        self._float(row.get("SMA20", 0)),
                    "sma50":        self._float(row.get("SMA50", 0)),
                    "sma200":       self._float(row.get("SMA200", 0)),
                    "perf_week":    self._pct(row.get("Perf Week", "0%")),
                    "perf_month":   self._pct(row.get("Perf Month", "0%")),
                    "perf_quarter": self._pct(row.get("Perf Quart", "0%")),
                    "perf_half":    self._pct(row.get("Perf Half", "0%")),
                    "perf_year":    self._pct(row.get("Perf Year", "0%")),
                    "perf_ytd":     self._pct(row.get("Perf YTD", row.get("Perf Year", "0%"))),
                    "52w_high":     self._float(row.get("52W High", 0)),
                    "52w_low":      self._float(row.get("52W Low", 0)),
                    "rsi":          self._float(row.get("RSI (14)", row.get("RSI", result[ticker].get("rsi", 50)))),
                })
        except Exception as e:
            print(f"  Finviz v=170 error: {e}")
            # Don't return empty — v=111 data is still useful

        # --- Request 3: v=161 ownership (inst trans, short float) ---
        try:
            resp3 = requests.get(f"{base_url}&v=161", timeout=15)
            resp3.raise_for_status()
            df3 = pd.read_csv(StringIO(resp3.text))
            for _, row in df3.iterrows():
                ticker = str(row.get("Ticker", "")).strip()
                if not ticker or ticker not in result:
                    continue
                result[ticker].update({
                    "institutional_own":       self._pct(row.get("Inst Own", "0%")),
                    "institutional_trans":     self._pct(row.get("Inst Trans", "0%")),
                    "institutional_trans_pct": self._pct(row.get("Inst Trans", "0%")),
                    "short_float":             self._pct(row.get("Short Float", "0%")),
                    "short_ratio":             self._float(row.get("Short Ratio", 0)),
                    "insider_own":             self._pct(row.get("Insider Own", "0%")),
                })
        except Exception as e:
            print(f"  Finviz v=161 error: {e}")

        print(f"  Finviz: fetched data for {len(result)} tickers")
        # Log sample for first ticker
        if result:
            sample = next(iter(result.values()))
            print(f"  Finviz sample: price={sample.get('price')} sma50={sample.get('sma50')} perf_q={sample.get('perf_quarter')} perf_h={sample.get('perf_half')}")
        return result


    def get_sector_etf_data(self, etf_symbols: list) -> dict:
        """Fetch ETF-level data for sector scoring."""
        return self.get_ticker_data(etf_symbols)

    def _pct(self, val) -> float:
        try:
            return float(str(val).replace("%", "").replace(",", "").strip())
        except:
            return 0.0

    def _float(self, val) -> float:
        try:
            s = str(val).replace(",", "").replace("%", "").strip()
            # Handle Finviz shorthand: 1.5B, 234.5M, etc.
            if s.endswith("B"):
                return float(s[:-1]) * 1e9
            if s.endswith("M"):
                return float(s[:-1]) * 1e6
            if s.endswith("K"):
                return float(s[:-1]) * 1e3
            return float(s)
        except:
            return 0.0


# ============================================================
# TRADIER OPTIONS CLIENT
# ============================================================

class TradierOptionsClient:
    """
    Tradier API client for options flow data.
    Used for unusual activity detection in scanner and scoring.
    """
    BASE_URL = "https://api.tradier.com/v1"

    def __init__(self):
        self.api_key = os.getenv("TRADIER_API_KEY") or os.getenv("TRADIER_TOKEN")
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
        } if self.api_key else {}

    def get_flow_for_ticker(self, symbol: str) -> dict:
        if not self.api_key:
            return self._empty_flow()
        try:
            resp = requests.get(
                f"{self.BASE_URL}/markets/options/chains",
                headers=self.headers,
                params={"symbol": symbol, "expiration": self._nearest_expiry(), "greeks": "false"},
                timeout=5,
            )
            if resp.status_code != 200:
                return self._empty_flow()
            options = resp.json().get("options", {}).get("option", []) or []
            calls = [o for o in options if o.get("option_type") == "call"]
            puts  = [o for o in options if o.get("option_type") == "put"]
            call_vol = sum(int(o.get("volume") or 0) for o in calls)
            put_vol  = sum(int(o.get("volume") or 0) for o in puts)
            total    = call_vol + put_vol
            return {
                "call_vol": call_vol,
                "put_vol": put_vol,
                "total_vol": total,
                "call_pct": round(call_vol / total * 100, 1) if total > 0 else 50,
                "bullish_flow": call_vol > put_vol,
                "put_call_ratio": round(put_vol / call_vol, 2) if call_vol > 0 else 99,
            }
        except Exception as e:
            print(f"  Tradier flow error {symbol}: {e}")
            return self._empty_flow()

    def get_unusual_activity(self, symbol: str) -> dict:
        flow = self.get_flow_for_ticker(symbol)
        total = flow.get("total_vol", 0)
        return {
            "unusual": total > 500 and flow.get("put_call_ratio", 1) != 1,
            "sweep_count": 0,
            "total_unusual": 1 if total > 500 else 0,
        }

    def _nearest_expiry(self) -> str:
        from datetime import date, timedelta
        d = date.today()
        # Find next Friday
        days_ahead = 4 - d.weekday()
        if days_ahead <= 0:
            days_ahead += 7
        return (d + timedelta(days=days_ahead)).isoformat()

    def _empty_flow(self) -> dict:
        return {
            "call_vol": 0, "put_vol": 0, "total_vol": 0,
            "call_pct": 50, "bullish_flow": False, "put_call_ratio": 1.0,
        }
