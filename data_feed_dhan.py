# data_feed_dhan.py — Full Dhan API (Data subscription active)

import requests
import pandas as pd
from datetime import datetime, timedelta
from logger import get_logger
import config

log      = get_logger("DhanFeed")
BASE_URL = "https://api.dhan.co"


class DhanDataFeed:
    """
    All market data from Dhan API (Data subscription required):
      - NIFTY spot price    → /v2/marketfeed/ltp
      - 5-min candles       → /v2/charts/intraday
      - Options chain       → /v2/optionchain
    """

    def __init__(self, dhan_client):
        self.dhan    = dhan_client
        self.headers = {
            "access-token": config.DHAN["access_token"],
            "client-id"   : config.DHAN["client_id"],
            "Content-Type": "application/json",
            "Accept"      : "application/json",
        }

    def _post(self, endpoint: str, body: dict) -> dict:
        url  = f"{BASE_URL}{endpoint}"
        resp = requests.post(url, json=body, headers=self.headers, timeout=15)
        resp.raise_for_status()
        return resp.json()

    # ─── SPOT PRICE ───────────────────────────────────────────────────────

    def get_spot_price(self) -> float:
        """
        Get NIFTY spot price.
        Tries Dhan LTP API first, falls back to last candle close.
        """
        # Method 1: Try Dhan market feed (NSE_INDEX format)
        for body in [
            {"NSE_INDEX": ["NIFTY 50"]},
            {config.NIFTY_INDEX_SEGMENT: [config.NIFTY_SECURITY_ID]},
            {"IDX_I": ["13"]},
        ]:
            try:
                data  = self._post("/v2/marketfeed/ltp", body)
                # Try to find price anywhere in response
                raw = data.get("data", {})
                for seg in raw.values():
                    if isinstance(seg, dict):
                        for item in seg.values():
                            if isinstance(item, dict):
                                p = item.get("last_price", 0)
                                if p and float(p) > 10000:
                                    log.info(f"NIFTY spot (LTP API): {p:.2f}")
                                    return float(p)
            except Exception:
                continue

        # Method 2: Fall back to last candle close (always works)
        try:
            df = self.get_historical_candles(minutes=10)
            if not df.empty:
                price = float(df["close"].iloc[-1])
                log.info(f"NIFTY spot (last candle): {price:.2f}")
                return price
        except Exception as e:
            log.error(f"get_spot_price fallback error: {e}")

        return 0.0

    # ─── HISTORICAL 5-MIN CANDLES ─────────────────────────────────────────

    def get_historical_candles(self, minutes: int = 800) -> pd.DataFrame:
        try:
            to_dt   = datetime.now()
            from_dt = to_dt - timedelta(days=15)

            data    = self._post("/v2/charts/intraday", {
                "securityId"     : config.NIFTY_SECURITY_ID,
                "exchangeSegment": config.NIFTY_INDEX_SEGMENT,
                "instrument"     : "INDEX",
                "interval"       : "5",
                "fromDate"       : from_dt.strftime("%Y-%m-%d"),
                "toDate"         : to_dt.strftime("%Y-%m-%d"),
            })

            candles    = data.get("data", data)
            timestamps = candles.get("timestamp", [])

            if not timestamps:
                log.warning("No candle data returned from Dhan")
                return pd.DataFrame()

            df = pd.DataFrame({
                "date"  : pd.to_datetime(timestamps, unit="s"),
                "open"  : candles.get("open",   []),
                "high"  : candles.get("high",   []),
                "low"   : candles.get("low",    []),
                "close" : candles.get("close",  []),
                "volume": candles.get("volume", []),
            })

            # Convert epoch to IST
            df["date"] = df["date"] + pd.Timedelta(hours=5, minutes=30)
            df = df.sort_values("date").reset_index(drop=True)
            df = df[df["date"].dt.time >= pd.Timestamp("09:15").time()]
            df = df.tail(minutes // 5)

            log.info(f"Fetched {len(df)} candles | Last close: {df['close'].iloc[-1]:.0f}")
            return df

        except Exception as e:
            log.error(f"get_historical_candles error: {e}")
            return pd.DataFrame()

    # ─── OPTIONS CHAIN ────────────────────────────────────────────────────

    def get_atm_strike(self, spot: float) -> int:
        return int(round(spot / config.STRIKE_STEP) * config.STRIKE_STEP)

    def get_nearest_expiry(self) -> str:
        """
        Fetch nearest valid expiry from Dhan's expiry list API.
        Falls back to next Monday if API fails (NSE moved NIFTY weekly expiry to Monday).
        """
        try:
            resp = self._post("/v2/optionchain/expirylist", {
                "UnderlyingScrip": int(config.NIFTY_SECURITY_ID),
                "UnderlyingSeg"  : config.NIFTY_INDEX_SEGMENT,
            })
            expiries = resp.get("data", [])
            if expiries:
                nearest = expiries[0]  # already sorted nearest first
                log.info(f"Expiry from Dhan list: {nearest} (total: {len(expiries)})")
                return nearest
        except Exception as e:
            log.warning(f"Expiry list fetch failed: {e} — using fallback")

        # Fallback: next Monday (NIFTY weekly expiry moved to Monday in 2024)
        today       = datetime.now()
        days_to_mon = (7 - today.weekday()) % 7 or 7
        expiry_dt   = today + timedelta(days=days_to_mon)
        return expiry_dt.strftime("%Y-%m-%d")

    def get_nearest_expiry_dhan(self) -> str:
        return self.get_nearest_expiry()  # now always YYYY-MM-DD

    def get_option_chain_data(self, spot: float) -> dict:
        try:
            atm         = self.get_atm_strike(spot)
            expiry_iso  = self.get_nearest_expiry()       # YYYY-MM-DD
            expiry_dhan = self.get_nearest_expiry_dhan()  # DD-MMM-YYYY

            # Try multiple body formats for option chain
            resp_data = None

            # Method 1: dhanhq SDK — YYYY-MM-DD (confirmed by Dhan docs)
            try:
                sdk_resp = self.dhan.option_chain(
                    under_security_id      = int(config.NIFTY_SECURITY_ID),
                    under_exchange_segment = config.NIFTY_INDEX_SEGMENT,
                    expiry                 = expiry_iso,
                )
                if sdk_resp and sdk_resp.get("data"):
                    resp_data = sdk_resp
                    log.info(f"Option chain fetched via SDK (expiry={expiry_iso})")
            except Exception as e:
                log.debug(f"SDK option_chain failed: {e}")

            # Method 3: Raw POST fallback
            if not resp_data:
                for body in [
                    {"UnderlyingScrip": int(config.NIFTY_SECURITY_ID),
                     "UnderlyingSeg"  : config.NIFTY_INDEX_SEGMENT,
                     "Expiry"         : expiry_dhan},
                    {"UnderlyingScrip": int(config.NIFTY_SECURITY_ID),
                     "UnderlyingSeg"  : config.NIFTY_INDEX_SEGMENT,
                     "Expiry"         : expiry_iso},
                ]:
                    try:
                        r = self._post("/v2/optionchain", body)
                        if r and r.get("data"):
                            resp_data = r
                            break
                    except Exception:
                        continue

            if not resp_data:
                raise Exception("All option chain formats failed")

            # SDK wraps response in extra 'data' layer — unwrap both levels
            level1 = resp_data.get("data", {})
            # Handle double-nesting: {"data": {"data": {...}, "status": ...}}
            if isinstance(level1, dict) and "data" in level1:
                inner = level1.get("data", {})
            else:
                inner = level1
            oc = inner.get("oc", {}) if isinstance(inner, dict) else {}
            if oc:
                log.info(f"OC loaded: {len(oc)} strikes | sample key: {list(oc.keys())[0]}")
            atm_ce = self._parse(oc, atm,                              "ce")
            atm_pe = self._parse(oc, atm,                              "pe")
            otm_ce = self._parse(oc, atm + config.SPREAD_WIDTH_POINTS, "ce")
            otm_pe = self._parse(oc, atm - config.SPREAD_WIDTH_POINTS, "pe")

            ce_vol    = atm_ce.get("volume", 1)
            pe_vol    = atm_pe.get("volume", 1)
            vol_ratio = pe_vol / ce_vol if ce_vol > 0 else 1.0

            log.info(
                f"Options | ATM={atm} expiry={expiry_dhan} | "
                f"CE ltp={atm_ce['ltp']:.1f} iv={atm_ce['iv']:.1f} | "
                f"PE ltp={atm_pe['ltp']:.1f} iv={atm_pe['iv']:.1f} | "
                f"vol_ratio={vol_ratio:.3f}"
            )

            return {
                "spot"     : spot,
                "atm"      : atm,
                "expiry"   : expiry_dhan,
                "timestamp": datetime.now(),
                "ce"       : atm_ce,
                "pe"       : atm_pe,
                "otm_ce"   : {**otm_ce, "strike": atm + config.SPREAD_WIDTH_POINTS},
                "otm_pe"   : {**otm_pe, "strike": atm - config.SPREAD_WIDTH_POINTS},
                "vol_ratio": round(vol_ratio, 4),
                "atm_vol"  : atm_ce.get("iv", 15) + atm_pe.get("iv", 15),
            }

        except Exception as e:
            log.error(f"get_option_chain_data error: {e}")
            return {}

    def _parse(self, oc: dict, strike: int, opt_type: str) -> dict:
        """
        Dhan option chain response structure:
        oc = { "24300.000000": { "ce": {...}, "pe": {...} }, ... }
        """
        # Strike key is stored as float string e.g. "24300.000000"
        strike_key = f"{float(strike):.6f}"
        row = oc.get(strike_key, {}).get(opt_type, {})

        return {
            "security_id": str(row.get("security_id", "")),
            "strike"     : strike,
            "ltp"        : float(row.get("last_price", 0)),
            "bid"        : float(row.get("top_bid_price", 0)),
            "ask"        : float(row.get("top_ask_price", 0)),
            "volume"     : int  (row.get("volume", 0)),
            "oi"         : int  (row.get("oi", 0)),
            "iv"         : float(row.get("implied_volatility", 15)),
        }

    def get_atm_options_snapshot(self, spot: float) -> dict:
        return self.get_option_chain_data(spot)
