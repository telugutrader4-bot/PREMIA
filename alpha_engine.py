# ═══════════════════════════════════════════════════════════════════════════
# alpha_engine.py — Alpha1 + Alpha2 Signal Generation
# ═══════════════════════════════════════════════════════════════════════════
#
#  ALPHA 1 — Price Momentum (time-series rank)
#    • 5-min price change normalized by day's open
#    • Ranked over last 800 minutes (160 candles)
#    • Range: 0 to 1  (0 = weakest, 1 = strongest move historically)
#
#  ALPHA 2 — Volume-Volatility Adjusted Signal
#    • Price change × (PE volume / CE volume) / ATM combined IV
#    • Ranked over last 300 minutes (60 candles)
#    • Range: 0 to 1
#
#  SIGNAL:
#    • Both alpha1 AND alpha2 > 0.8 → BULLISH → Open Put Spread
#    • Both alpha1 AND alpha2 < 0.2 → BEARISH → Open Call Spread
#    • Otherwise → NEUTRAL → No trade
#
# ═══════════════════════════════════════════════════════════════════════════

import pandas as pd
import numpy as np
from collections import deque
from datetime import datetime
from logger import get_logger
import config

log = get_logger("AlphaEngine")


class AlphaEngine:

    def __init__(self):
        # Rolling history buffers
        self.candle_history  = deque(maxlen=config.ALPHA1_LOOKBACK // 5 + 10)
        self.options_history = deque(maxlen=config.ALPHA2_LOOKBACK // 5 + 10)

        self.day_open     = None   # NIFTY open price for the day
        self.last_alpha1  = None
        self.last_alpha2  = None
        self.last_signal  = "NEUTRAL"

    # ─── FEED NEW DATA ────────────────────────────────────────────────────

    def update_candle(self, candle: dict):
        """
        Feed a new 5-min candle.
        candle = {datetime, open, high, low, close, volume}
        """
        # Track day open
        if self.day_open is None or candle["datetime"].hour == 9 and candle["datetime"].minute == 15:
            self.day_open = candle["open"]

        self.candle_history.append(candle)
        log.debug(f"Candle added: {candle['datetime']} C={candle['close']}")

    def update_options(self, snapshot: dict):
        """
        Feed a new options snapshot.
        snapshot = {spot, atm, ce:{ltp,volume,iv}, pe:{ltp,volume,iv}, atm_vol, vol_ratio, timestamp}
        """
        self.options_history.append(snapshot)
        log.debug(f"Options snapshot added: ATM={snapshot['atm']} vol_ratio={snapshot['vol_ratio']:.3f}")

    # ─── ALPHA 1 ──────────────────────────────────────────────────────────

    def _compute_alpha1(self) -> float:
        """
        Alpha1 = time-series percentile rank of current 5-min price move.

        Formula:
          price_change[i] = (close[i] - close[i-1]) / day_open
          alpha1 = rank(current_price_change, last 800 min of changes)

        Returns float 0..1  or None if not enough data.
        """
        if len(self.candle_history) < 5:
            log.debug("Not enough candles for alpha1")
            return None

        candles = list(self.candle_history)
        closes  = np.array([c["close"] for c in candles])
        day_open = self.day_open if self.day_open else closes[0]

        # 5-min price changes normalized by day open
        changes = np.diff(closes) / day_open
        if len(changes) < 2:
            return None

        current_change = changes[-1]
        history_changes = changes[:-1]

        # Percentile rank: what % of historical changes is current below?
        rank = float(np.sum(history_changes < current_change) / len(history_changes))

        log.debug(f"Alpha1: change={current_change:.5f} rank={rank:.3f} "
                  f"(over {len(history_changes)} observations)")
        return rank

    # ─── ALPHA 2 ──────────────────────────────────────────────────────────

    def _compute_alpha2(self) -> float:
        """
        Alpha2 = time-series percentile rank of volume-volatility adjusted signal.

        Formula:
          raw_signal[i] = price_change[i] × vol_ratio[i] / atm_iv[i]
          alpha2 = rank(current_raw_signal, last 300 min of signals)

        vol_ratio  = PE volume / CE volume  (>1 means put-heavy, bearish sentiment)
        atm_iv     = CE IV + PE IV  (combined ATM volatility)

        Returns float 0..1  or None if not enough data.
        """
        if len(self.options_history) < 5 or len(self.candle_history) < 2:
            log.debug("Not enough options data for alpha2")
            return None

        opts    = list(self.options_history)
        candles = list(self.candle_history)

        # Align lengths
        min_len = min(len(opts), len(candles) - 1)
        if min_len < 2:
            return None

        opts    = opts[-min_len:]
        closes  = [c["close"] for c in candles[-(min_len + 1):]]
        day_open = self.day_open if self.day_open else closes[0]

        raw_signals = []
        for i in range(min_len):
            price_chg  = (closes[i + 1] - closes[i]) / day_open
            vol_ratio  = opts[i].get("vol_ratio", 1.0)
            atm_iv     = opts[i].get("atm_vol",   1.0)

            if atm_iv == 0:
                atm_iv = 0.001   # avoid division by zero

            raw = price_chg * vol_ratio / atm_iv
            raw_signals.append(raw)

        if len(raw_signals) < 2:
            return None

        current_raw = raw_signals[-1]
        history_raw = raw_signals[:-1]

        # Percentile rank
        rank = float(np.sum(np.array(history_raw) < current_raw) / len(history_raw))

        log.debug(f"Alpha2: raw={current_raw:.5f} rank={rank:.3f} "
                  f"(over {len(history_raw)} observations)")
        return rank

    # ─── SIGNAL GENERATION ────────────────────────────────────────────────

    def generate_signal(self) -> dict:
        """
        Compute alpha1 and alpha2, then return signal.

        Returns:
          {
            "signal"  : "BULLISH" | "BEARISH" | "NEUTRAL",
            "alpha1"  : float,
            "alpha2"  : float,
            "strength": float,   # average of both alphas
            "timestamp": datetime
          }
        """
        alpha1 = self._compute_alpha1()
        alpha2 = self._compute_alpha2()

        self.last_alpha1 = alpha1
        self.last_alpha2 = alpha2

        # Need both to generate signal
        if alpha1 is None or alpha2 is None:
            result = {
                "signal"   : "NEUTRAL",
                "alpha1"   : alpha1,
                "alpha2"   : alpha2,
                "strength" : 0.0,
                "reason"   : "Insufficient data",
                "timestamp": datetime.now()
            }
            log.info(f"Signal: NEUTRAL (insufficient data)")
            return result

        strength = (alpha1 + alpha2) / 2

        if alpha1 >= config.BULL_THRESHOLD and alpha2 >= config.BULL_THRESHOLD:
            signal = "BULLISH"
            reason = f"Both alphas > {config.BULL_THRESHOLD} → Strong upward momentum"

        elif alpha1 <= config.BEAR_THRESHOLD and alpha2 <= config.BEAR_THRESHOLD:
            signal = "BEARISH"
            reason = f"Both alphas < {config.BEAR_THRESHOLD} → Strong downward momentum"

        else:
            signal = "NEUTRAL"
            reason = f"Alphas not aligned (a1={alpha1:.2f}, a2={alpha2:.2f})"

        self.last_signal = signal

        result = {
            "signal"   : signal,
            "alpha1"   : round(alpha1,  4),
            "alpha2"   : round(alpha2,  4),
            "strength" : round(strength, 4),
            "reason"   : reason,
            "timestamp": datetime.now()
        }

        log.info(f"Signal: {signal} | a1={alpha1:.3f} a2={alpha2:.3f} "
                 f"strength={strength:.3f} | {reason}")
        return result

    # ─── STATUS ───────────────────────────────────────────────────────────

    def status(self) -> dict:
        return {
            "candles_loaded" : len(self.candle_history),
            "options_loaded" : len(self.options_history),
            "last_alpha1"    : self.last_alpha1,
            "last_alpha2"    : self.last_alpha2,
            "last_signal"    : self.last_signal,
            "day_open"       : self.day_open,
        }

    def reset_day(self):
        """Call at start of each new trading day."""
        self.day_open    = None
        self.last_signal = "NEUTRAL"
        log.info("Alpha engine reset for new day")
