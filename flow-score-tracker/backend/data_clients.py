# Last updated: 2026-03-18 12:20 ET 
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

        # --- Request 2: v=141 Performance (perf fields, rel vol) ---
        try:
            resp2 = requests.get(f"{base_url}&v=141", timeout=15)
            resp2.raise_for_status()
            df2 = pd.read_csv(StringIO(resp2.text))
            print(f"  Finviz v=141 columns: {list(df2.columns)}")
            for _, row in df2.iterrows():
                ticker = str(row.get("Ticker", "")).strip()
                if not ticker or ticker not in result:
                    continue
                result[ticker].update({
                    "perf_week":       self._pct(row.get("Performance (Week)", "0%")),
                    "perf_month":      self._pct(row.get("Performance (Month)", "0%")),
                    "perf_quarter":    self._pct(row.get("Performance (Quarter)", "0%")),
                    "perf_half":       self._pct(row.get("Performance (Half Year)", "0%")),
                    "perf_year":       self._pct(row.get("Performance (Year)", "0%")),
                    "perf_ytd":        self._pct(row.get("Performance (YTD)", "0%")),
                    "relative_volume": self._float(row.get("Relative Volume", 0)),
                    "avg_volume":      self._float(row.get("Average Volume", 0)),
                })
        except Exception as e:
            print(f"  Finviz v=141 error: {e}")

        # --- Request 3: SMA data via TradingView screener ---
        # Finviz export API has no SMA columns. TradingView screener returns
        # SMA20/50/200 reliably during market hours.
        tv_symbols = [s for s in result.keys() if len(s) <= 5 and s != "SPY"]
        if tv_symbols:
            try:
                from tradingview_screener import Query, col as tv_col
                import time
                time.sleep(1.0)  # pause after Finviz requests to avoid rate limiting
                for ticker in tv_symbols:
                    try:
                        _, df_s = (Query()
                            .select("name", "close", "SMA20", "SMA50", "SMA200", "RSI", "High.52W", "Low.52W")
                            .set_markets("america")
                            .where(tv_col("name").isin([ticker]))
                            .limit(3)
                            .get_scanner_data()
                        )
                        if len(df_s) > 0:
                            row = df_s.iloc[0]
                            result[ticker].update({
                                "sma20":    round(float(row["SMA20"] or 0), 2),
                                "sma50":    round(float(row["SMA50"] or 0), 2),
                                "sma200":   round(float(row["SMA200"] or 0), 2),
                                "rsi":      float(row["RSI"] or 50),
                                "52w_high": float(row["High.52W"] or 0),
                                "52w_low":  float(row["Low.52W"] or 0),
                            })
                            print(f"  SMA OK {ticker}: sma50={result[ticker]['sma50']}")
                        else:
                            print(f"  SMA empty {ticker}: 0 rows returned")
                        time.sleep(0.3)
                    except Exception as e:
                        print(f"  SMA error {ticker}: {e}")
            except Exception as e:
                print(f"  TV import error: {e}")

        # --- Request 4: v=131 Ownership (Inst Trans, Short Float) ---
        try:
            resp4 = requests.get(f"{base_url}&v=131", timeout=15)
            resp4.raise_for_status()
            df4 = pd.read_csv(StringIO(resp4.text))
            for _, row in df4.iterrows():
                ticker = str(row.get("Ticker", "")).strip()
                if not ticker or ticker not in result:
                    continue
                result[ticker].update({
                    "institutional_own":       self._pct(row.get("Inst Own", row.get("Institutional Ownership", "0%"))),
                    "institutional_trans":     self._pct(row.get("Inst Trans", row.get("Institutional Transactions", "0%"))),
                    "institutional_trans_pct": self._pct(row.get("Inst Trans", row.get("Institutional Transactions", "0%"))),
                    "short_float":             self._pct(row.get("Short Float", "0%")),
                    "short_ratio":             self._float(row.get("Short Ratio", 0)),
                    "insider_own":             self._pct(row.get("Insider Own", row.get("Insider Ownership", "0%"))),
                })
        except Exception as e:
            print(f"  Finviz v=131 error: {e}")

        print(f"  Finviz: fetched data for {len(result)} tickers")
        # Log sample for first ticker
        if result:
            sample = next(iter(result.values()))
            print(f"  Finviz sample: price={sample.get('price')} sma50={sample.get('sma50')} perf_q={sample.get('perf_quarter')} perf_h={sample.get('perf_half')}")
        return result


    def get_sector_etf_data(self, etf_symbols: list) -> dict:
        """Fetch ETF-level data for sector scoring."""
        return self.get_ticker_data(etf_symbols)

    def get_sma_data(self, symbols: list) -> dict:
        """
        Fetch SMA20/50/200 for a list of tickers via TradingView screener.
        Returns dict keyed by ticker with sma20/sma50/sma200/rsi/52w_high/52w_low.
        """
        if not symbols:
            return {}
        try:
            from tradingview_screener import Query, col as tv_col
            import time
            time.sleep(0.5)  # brief pause to avoid rate limiting after Finviz calls
            _, df = (Query()
                .select("name", "close", "SMA20", "SMA50", "SMA200", "RSI", "High.52W", "Low.52W")
                .set_markets("america")
                .where(tv_col("name").isin(symbols))
                .limit(len(symbols) + 10)
                .get_scanner_data()
            )
            result = {}
            for _, row in df.iterrows():
                ticker = str(row["name"]).strip()
                result[ticker] = {
                    "sma20":    round(float(row["SMA20"]  or 0), 2),
                    "sma50":    round(float(row["SMA50"]  or 0), 2),
                    "sma200":   round(float(row["SMA200"] or 0), 2),
                    "rsi":      float(row["RSI"] or 50),
                    "52w_high": float(row["High.52W"] or 0),
                    "52w_low":  float(row["Low.52W"] or 0),
                }
            print(f"  get_sma_data: {len(result)}/{len(symbols)} tickers. Sample: {list(result.items())[:1]}")
            return result
        except Exception as e:
            print(f"  get_sma_data error: {e}")
            return {}

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
    # Production by default; set TRADIER_BASE_URL=https://sandbox.tradier.com/v1
    # in the env when using a sandbox token.
    BASE_URL = os.getenv("TRADIER_BASE_URL", "https://api.tradier.com/v1")

    def __init__(self):
        self.api_key = (os.getenv("TRADIER_API_KEY") or os.getenv("TRADIER_TOKEN") or "").strip() or None
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

    def get_expirations(self, symbol: str) -> list:
        """All available expiration dates (ISO strings) for a symbol."""
        if not self.api_key:
            return []
        try:
            resp = requests.get(
                f"{self.BASE_URL}/markets/options/expirations",
                headers=self.headers,
                params={"symbol": symbol, "includeAllRoots": "true"},
                timeout=6,
            )
            if resp.status_code != 200:
                return []
            exp = (resp.json().get("expirations") or {}).get("date", []) or []
            return exp if isinstance(exp, list) else [exp]
        except Exception as e:
            print(f"  Tradier expirations error {symbol}: {e}")
            return []

    def pick_expiration(self, symbol: str, dte_target: int, dte_min: int, dte_max: int) -> str:
        """Closest available expiration to dte_target within a tolerant window."""
        from datetime import date
        today = date.today()
        best, best_diff = None, 1e9
        for e in self.get_expirations(symbol):
            try:
                dte = (date.fromisoformat(e) - today).days
            except Exception:
                continue
            if dte < dte_min - 10:   # allow some slack below the floor
                continue
            diff = abs(dte - dte_target)
            if diff < best_diff:
                best, best_diff = e, diff
        return best

    def get_option_chain(self, symbol: str, expiration: str) -> list:
        """Full option chain for one expiration, with greeks (delta, IV)."""
        if not self.api_key:
            return []
        try:
            resp = requests.get(
                f"{self.BASE_URL}/markets/options/chains",
                headers=self.headers,
                params={"symbol": symbol, "expiration": expiration, "greeks": "true"},
                timeout=8,
            )
            if resp.status_code != 200:
                return []
            opts = (resp.json().get("options") or {}).get("option", []) or []
            return opts if isinstance(opts, list) else [opts]
        except Exception as e:
            print(f"  Tradier chain error {symbol}: {e}")
            return []

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


# ============================================================
# ETF FLOW CLIENT — creation/redemption flow via shares outstanding
# ============================================================

class EtfFlowClient:
    """
    Snapshots an ETF's AUM and NAV (via the TradingView screener, already a
    project dependency) so the pipeline can compute real creation/redemption flow.

    ETFs don't expose a raw share count through the screener, but AUM is well
    corroborated across sources, so we derive implied shares = AUM / price.
    Net flow = delta(shares) * price isolates creation/redemption from price
    appreciation; Flow/AUM% = delta(shares)/shares. yfinance was avoided because
    its websockets>=13 dependency conflicts with the pinned supabase realtime.
    History accrues forward (the pipeline persists a weekly snapshot).
    """

    def get_snapshot(self, tickers: list) -> dict:
        """Return {ticker: {shares, price, aum}} of current values."""
        from tradingview_screener import Query, col
        out = {}
        try:
            _, df = (Query()
                .select("name", "close", "aum")
                .set_markets("america")
                .where(col("name").isin(list(tickers)))
                .limit(len(tickers) + 10)
                .get_scanner_data())
        except Exception as e:
            print(f"  ETF snapshot query error: {e}")
            return out
        for _, r in df.iterrows():
            t = str(r["name"]).strip()
            try:
                aum = float(r["aum"]); price = float(r["close"])
            except (TypeError, ValueError, KeyError):
                continue
            if aum > 0 and price > 0:
                out[t] = {"shares": aum / price, "price": price, "aum": aum}
            else:
                print(f"  ETF snapshot {t}: missing aum/price")
        return out


# ============================================================
# TRADESTATION OPTIONS CLIENT
# Live option chains with greeks. Normalizes to the same shape the grader
# expects (option_type / strike / bid / ask / open_interest / volume /
# greeks{delta, mid_iv}), so it's a drop-in for the Tradier client.
# ============================================================

class TradeStationClient:
    SIGNIN = "https://signin.tradestation.com/oauth/token"
    BASE = os.getenv("TRADESTATION_BASE_URL", "https://api.tradestation.com")

    # Class-level token cache — survives across per-request instances.
    _token = None
    _token_exp = 0.0

    def __init__(self):
        self.client_id = (os.getenv("TRADESTATION_CLIENT_ID") or "").strip() or None
        self.client_secret = (os.getenv("TRADESTATION_CLIENT_SECRET") or "").strip() or None
        self.refresh_token = (os.getenv("TRADESTATION_REFRESH_TOKEN") or "").strip() or None

    @property
    def configured(self) -> bool:
        return bool(self.client_id and self.client_secret and self.refresh_token)

    def _access_token(self):
        import time
        now = time.time()
        if TradeStationClient._token and now < TradeStationClient._token_exp - 60:
            return TradeStationClient._token
        if not self.configured:
            return None
        try:
            r = requests.post(self.SIGNIN, data={
                "grant_type": "refresh_token", "client_id": self.client_id,
                "client_secret": self.client_secret, "refresh_token": self.refresh_token,
            }, headers={"Content-Type": "application/x-www-form-urlencoded"}, timeout=12)
            if r.status_code != 200:
                print(f"  TradeStation token refresh {r.status_code}: {r.text[:140]}")
                return None
            j = r.json()
            TradeStationClient._token = j.get("access_token")
            TradeStationClient._token_exp = now + int(j.get("expires_in", 1200))
            return TradeStationClient._token
        except Exception as e:
            print(f"  TradeStation token error: {e}")
            return None

    def get_expirations(self, symbol: str) -> list:
        token = self._access_token()
        if not token:
            return []
        try:
            r = requests.get(f"{self.BASE}/v3/marketdata/options/expirations/{symbol}",
                             headers={"Authorization": f"Bearer {token}"}, timeout=10)
            if r.status_code != 200:
                print(f"  TradeStation expirations {symbol} {r.status_code}")
                return []
            return [e["Date"][:10] for e in r.json().get("Expirations", []) if e.get("Date")]
        except Exception as e:
            print(f"  TradeStation expirations error {symbol}: {e}")
            return []

    def pick_expiration(self, symbol: str, dte_target: int, dte_min: int, dte_max: int) -> str:
        from datetime import date
        today = date.today()
        best, best_diff = None, 1e9
        for e in self.get_expirations(symbol):
            try:
                dte = (date.fromisoformat(e) - today).days
            except Exception:
                continue
            if dte < dte_min - 10:
                continue
            if abs(dte - dte_target) < best_diff:
                best, best_diff = e, abs(dte - dte_target)
        return best

    @staticmethod
    def _f(x):
        try:
            return float(x)
        except (TypeError, ValueError):
            return 0.0

    def _normalize(self, obj: dict) -> dict:
        leg = (obj.get("Legs") or [{}])[0]
        return {
            "option_type": (leg.get("OptionType") or obj.get("Side") or "").lower(),
            "symbol": leg.get("Symbol"),
            "strike": self._f(leg.get("StrikePrice")),
            "expiration_date": (leg.get("Expiration") or "")[:10],
            "bid": self._f(obj.get("Bid")), "ask": self._f(obj.get("Ask")),
            "last": self._f(obj.get("Last")),
            "open_interest": int(obj.get("DailyOpenInterest") or 0),
            "volume": int(obj.get("Volume") or 0),
            "greeks": {"delta": self._f(obj.get("Delta")),
                       "mid_iv": self._f(obj.get("ImpliedVolatility"))},
        }

    def get_option_chain(self, symbol: str, expiration: str, strike_proximity: int = 20) -> list:
        """Stream the chain for one expiration, return normalized CALL contracts."""
        import json as _json, time
        token = self._access_token()
        if not token:
            return []
        calls, seen = [], set()
        start = time.time()
        try:
            with requests.get(
                f"{self.BASE}/v3/marketdata/stream/options/chains/{symbol}",
                headers={"Authorization": f"Bearer {token}"},
                params={"expiration": expiration, "strikeProximity": str(strike_proximity)},
                stream=True, timeout=20,
            ) as s:
                for line in s.iter_lines():
                    if time.time() - start > 14:      # overall time budget
                        break
                    if not line:
                        continue
                    try:
                        obj = _json.loads(line)
                    except Exception:
                        continue
                    if "Heartbeat" in obj or "Error" in obj or "StreamStatus" in obj:
                        if calls:                     # snapshot delivered -> done
                            break
                        continue
                    leg = (obj.get("Legs") or [{}])[0]
                    if leg.get("OptionType") != "Call":
                        continue
                    strike = leg.get("StrikePrice")
                    if strike in seen:                # stream looped -> snapshot done
                        break
                    seen.add(strike)
                    calls.append(self._normalize(obj))
                    if len(calls) >= strike_proximity * 2 + 1:
                        break
        except Exception as e:
            print(f"  TradeStation chain error {symbol}: {e}")
        return calls
