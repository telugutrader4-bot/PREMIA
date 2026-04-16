#!/usr/bin/env python3
# ═══════════════════════════════════════════════════════════════════════════
# main.py — PREMIA | Fully Automated | Dhan + Telegram
# ═══════════════════════════════════════════════════════════════════════════
#
#  Run:  python main.py           → live trading (real orders)
#        python main.py --paper   → paper mode (real data, fake orders)
#
# KEY FIX: Paper mode now uses REAL Dhan data feed but FAKE order execution.
# This means signals and prices are real — only order placement is simulated.
# ═══════════════════════════════════════════════════════════════════════════

import time
import argparse
from datetime import datetime

import config
from logger            import get_logger
from broker_dhan       import DhanBroker, PaperBroker
from broker_1ly        import OneLYBroker
from data_feed_dhan    import DhanDataFeed
from alpha_engine      import AlphaEngine
from trade_constructor import TradeConstructor
from risk_manager      import RiskManager
import notifier

log = get_logger("Main")


# ─── TIME HELPERS ─────────────────────────────────────────────────────────

def now_time() -> str:
    return datetime.now().strftime("%H:%M")

def is_market_open() -> bool:
    t = now_time()
    return config.MARKET_OPEN <= t <= config.MARKET_CLOSE

def is_new_day(last_date) -> bool:
    return datetime.now().date() != last_date

def seconds_to_next_candle() -> int:
    """Wait until next 5-minute boundary."""
    now  = datetime.now()
    wait = (5 - now.minute % 5) * 60 - now.second
    return max(wait, 10)


# ─── MAIN ALGO ────────────────────────────────────────────────────────────

class PremiaAlgo:

    def __init__(self, paper_mode: bool = False):
        self.paper_mode = paper_mode
        use_1ly = config.ONELY.get("enabled", False)

        log.info("=" * 60)
        log.info("  PREMIA — Credit Spread Algo")
        if paper_mode:
            log.info("  Mode    : [PAPER] real data, fake orders")
        elif use_1ly:
            log.info("  Mode    : [1LY] real data, orders via 1LY webhook")
        else:
            log.info("  Mode    : [LIVE] real data, orders via Dhan")
        log.info(f"  Capital : Rs.{config.CAPITAL:,}")
        log.info("=" * 60)

        # Always connect real Dhan for market data (candles + options chain)
        self.real_dhan = DhanBroker()

        # Order execution broker — Paper / 1LY / Dhan Live
        if paper_mode:
            self.broker = PaperBroker()
        elif use_1ly:
            self.broker = OneLYBroker()
        else:
            self.broker = self.real_dhan

        self.feed    = DhanDataFeed(self.real_dhan.get_client())  # always real data
        self.alpha   = AlphaEngine()
        self.builder = TradeConstructor(data_feed=self.feed)
        self.risk    = RiskManager()

        self.active_position    = None
        self.last_date          = datetime.now().date()
        self.daily_summary_sent = False

    # ─── WARM UP ──────────────────────────────────────────────────────────

    def warmup(self):
        """Load historical candles to warm up alpha engine on startup."""
        log.info("Warming up alpha engine with historical NIFTY data...")
        df = self.feed.get_historical_candles(minutes=config.ALPHA1_LOOKBACK + 60)

        if df.empty:
            log.warning("No history loaded — alpha will accumulate data over time")
            return

        spot = self.feed.get_spot_price()
        snap = self.feed.get_atm_options_snapshot(spot) if spot else {}

        for _, row in df.iterrows():
            self.alpha.update_candle({
                "datetime": row["date"],
                "open"    : row["open"],
                "high"    : row["high"],
                "low"     : row["low"],
                "close"   : row["close"],
                "volume"  : row["volume"],
            })
            if snap:
                self.alpha.update_options(snap)

        log.info(f"Warmup done — {len(df)} candles | "
                 f"a1 ready: {self.alpha.last_alpha1} | a2 ready: {self.alpha.last_alpha2}")

    # ─── FETCH DATA ───────────────────────────────────────────────────────

    def fetch_and_update(self):
        spot = self.feed.get_spot_price()
        if not spot:
            log.error("Could not fetch NIFTY spot price from Dhan")
            return None

        df = self.feed.get_historical_candles(minutes=15)
        if df.empty:
            log.error("No candle data returned")
            return None

        row = df.iloc[-1]
        self.alpha.update_candle({
            "datetime": row["date"],
            "open"    : row["open"],
            "high"    : row["high"],
            "low"     : row["low"],
            "close"   : row["close"],
            "volume"  : row["volume"],
        })

        snap = self.feed.get_atm_options_snapshot(spot)
        if snap:
            self.alpha.update_options(snap)

        return snap

    # ─── MONITOR POSITION ─────────────────────────────────────────────────

    def monitor_position(self) -> bool:
        """
        Check all exit conditions on open position every 5 minutes.
        Exit order of priority:
          1. Stop Loss    — sell leg premium rose 50% above entry
          2. Max Loss     — total spread loss exceeds max_loss
          3. Profit Target— profit reached 50% of max profit (lock gains)
          4. Signal Exit  — alpha signal reversed against position direction
        Returns True if position was exited.
        """
        pos  = self.active_position
        sell = pos["sell_leg"]
        buy  = pos["buy_leg"]

        # Use real Dhan data even in paper mode
        current_sell = self.real_dhan.get_option_ltp(sell["security_id"])
        current_buy  = self.real_dhan.get_option_ltp(buy["security_id"])
        pnl          = self.risk.calculate_open_pnl(pos, current_sell, current_buy)

        sl_level = pos.get("stop_loss_premium", 0)
        log.info(f"Position | PnL=Rs.{pnl:+.0f} | "
                 f"Sell LTP={current_sell:.2f} (SL@{sl_level:.2f}) | "
                 f"Buy LTP={current_buy:.2f}")

        # ── 1. Stop Loss ──────────────────────────────────────────────────
        sl_hit, sl_reason = self.risk.check_stop_loss(pos, current_sell)
        if sl_hit:
            notifier.alert_stop_loss(pos, current_sell, pnl)
            self.broker.exit_spread(pos, reason=sl_reason)
            self.risk.record_trade_exit(pos, pnl, sl_reason)
            notifier.alert_trade_exit(pos, pnl, sl_reason)
            self.active_position = None
            return True

        # ── 2. Max Loss breach ────────────────────────────────────────────
        ml_hit, ml_reason = self.risk.check_max_loss_breach(pos, pnl)
        if ml_hit:
            notifier.alert_stop_loss(pos, current_sell, pnl)
            self.broker.exit_spread(pos, reason=ml_reason)
            self.risk.record_trade_exit(pos, pnl, ml_reason)
            notifier.alert_trade_exit(pos, pnl, ml_reason)
            self.active_position = None
            return True

        # ── 3. Profit Target ──────────────────────────────────────────────
        pt_hit, pt_reason = self.risk.check_profit_target(pos, pnl)
        if pt_hit:
            self.broker.exit_spread(pos, reason=pt_reason)
            self.risk.record_trade_exit(pos, pnl, pt_reason)
            notifier.alert_trade_exit(pos, pnl, pt_reason)
            self.active_position = None
            return True

        # ── 4. Signal Reversal ────────────────────────────────────────────
        current_signal = self.alpha.generate_signal()
        rev_hit, rev_reason = self.risk.check_signal_reversal(pos, current_signal["signal"])
        if rev_hit:
            self.broker.exit_spread(pos, reason=rev_reason)
            self.risk.record_trade_exit(pos, pnl, rev_reason)
            notifier.alert_trade_exit(pos, pnl, rev_reason)
            self.active_position = None
            return True

        return False

    # ─── ENTRY FILTERS ────────────────────────────────────────────────────

    def _entry_filters_pass(self, snap: dict, spread: dict) -> bool:
        """
        ZEN Credit Spread entry quality checks.
        All must pass before placing any order.
        """
        sell_leg = spread["sell_leg"]

        # 1. Net credit minimum — not worth the risk if too small
        if spread["net_credit"] < config.MIN_CREDIT_POINTS:
            log.info(f"SKIP | Net credit {spread['net_credit']} pts "
                     f"< min {config.MIN_CREDIT_POINTS} pts — premium too cheap")
            return False

        # 2. ATM IV check — don't sell when volatility is too low
        atm_iv = snap.get("atm_vol", 0) / 2   # atm_vol = CE IV + PE IV
        if atm_iv < config.MIN_ATM_IV:
            log.info(f"SKIP | ATM IV {atm_iv:.1f}% < min {config.MIN_ATM_IV}% — not worth selling")
            return False

        # 3. OI check — avoid illiquid strikes
        sell_oi = sell_leg.get("oi", 0)
        if sell_oi < config.MIN_ATM_OI:
            log.info(f"SKIP | Sell leg OI {sell_oi} < min {config.MIN_ATM_OI} — illiquid strike")
            return False

        # 4. Bid-Ask spread check — avoid wide spread (slippage risk)
        ltp = sell_leg.get("ltp", 0)
        bid = sell_leg.get("bid", 0)
        ask = sell_leg.get("ask", 0)
        if ltp > 0 and ask > 0 and bid > 0:
            ba_pct = (ask - bid) / ltp
            if ba_pct > config.MAX_BID_ASK_PCT:
                log.info(f"SKIP | Bid-ask spread {ba_pct*100:.1f}% "
                         f"> max {config.MAX_BID_ASK_PCT*100:.0f}% — wide market")
                return False

        log.info(f"Entry filters PASSED | credit={spread['net_credit']} | "
                 f"IV={atm_iv:.1f}% | OI={sell_oi}")
        return True

    # ─── SIGNAL + ENTRY ───────────────────────────────────────────────────

    def check_and_enter(self, snap: dict):
        # Gate 1: risk manager pre-trade checks
        can, reason = self.risk.can_trade()
        if not can:
            notifier.alert_no_trade(reason)
            return

        # Gate 2: alpha signal — both alphas must agree
        signal = self.alpha.generate_signal()
        if signal["signal"] == "NEUTRAL":
            log.info(f"NEUTRAL | a1={signal['alpha1']} a2={signal['alpha2']}")
            return

        spot = snap.get("spot", 0)
        notifier.alert_signal(signal, spot)

        # Gate 3: build the spread
        spread = self.builder.build_from_signal(signal, spot, snap)
        if not spread:
            return

        # Gate 4: entry quality filters (IV, credit, OI, bid-ask)
        if not self._entry_filters_pass(snap, spread):
            return

        # Size the position
        lots           = self.risk.get_lot_size(spread)
        spread["lots"] = lots
        spread["sell_leg"]["quantity"] = lots * config.LOT_SIZE
        spread["buy_leg"]["quantity"]  = lots * config.LOT_SIZE

        # Recompute max_profit/max_loss after lot sizing
        spread["max_profit"] = round(spread["net_credit"] * lots * config.LOT_SIZE, 2)
        spread["max_loss"]   = round(
            (config.SPREAD_WIDTH_POINTS - spread["net_credit"]) * lots * config.LOT_SIZE, 2
        )

        self.builder.print_spread_summary(spread)
        notifier.alert_trade_entry(spread)

        result = self.broker.place_spread(spread)

        if "FAIL" not in result.get("status", ""):
            self.active_position = spread
            self.risk.register_open_position(spread)
        else:
            msg = f"Order placement failed: {result}"
            log.error(msg)
            notifier.alert_error(msg)

    # ─── EXPIRY DAY CHECK ─────────────────────────────────────────────────

    def is_expiry_day(self) -> bool:
        """NIFTY weekly expiry is every Monday."""
        return datetime.now().weekday() == 0   # 0 = Monday

    def handle_expiry_exit(self):
        """
        On expiry day, force-close position before EXPIRY_EXIT_TIME (14:30).
        Options go to zero on expiry — must exit before that.
        """
        if not self.active_position:
            return
        if not self.is_expiry_day():
            return
        if now_time() < config.EXPIRY_EXIT_TIME:
            return

        pos      = self.active_position
        sell_ltp = self.real_dhan.get_option_ltp(pos["sell_leg"]["security_id"])
        buy_ltp  = self.real_dhan.get_option_ltp(pos["buy_leg"]["security_id"])
        pnl      = self.risk.calculate_open_pnl(pos, sell_ltp, buy_ltp)
        reason   = "EXPIRY DAY EXIT — closing before expiry"

        log.warning(f"Expiry day exit | PnL=Rs.{pnl:+.0f}")
        self.broker.exit_spread(pos, reason)
        self.risk.record_trade_exit(pos, pnl, reason)
        notifier.alert_trade_exit(pos, pnl, reason)
        self.active_position = None

    # ─── EOD SUMMARY (no force exit in positional mode) ───────────────────

    def end_of_day(self):
        """
        Positional strategy: do NOT close position at end of day.
        Position holds overnight and monitoring resumes next morning.
        Only send daily summary.
        """
        if self.active_position and not self.daily_summary_sent:
            pos      = self.active_position
            sell_ltp = self.real_dhan.get_option_ltp(pos["sell_leg"]["security_id"])
            buy_ltp  = self.real_dhan.get_option_ltp(pos["buy_leg"]["security_id"])
            pnl      = self.risk.calculate_open_pnl(pos, sell_ltp, buy_ltp)
            log.info(f"EOD | Position HELD OVERNIGHT | Open PnL=Rs.{pnl:+.0f} | "
                     f"Type={pos['type']} | Expiry={pos['expiry']}")
            notifier.alert_daily_summary({**self.risk.status(), "open_pnl": pnl})
        elif not self.daily_summary_sent:
            notifier.alert_daily_summary(self.risk.status())

        self.daily_summary_sent = True

    # ─── NEW DAY ──────────────────────────────────────────────────────────

    def new_day_reset(self):
        """
        Reset daily counters but KEEP the active position — it carried overnight.
        """
        log.info("New trading day — resetting daily counters")
        self.risk.reset_day()        # resets trades_today, daily_pnl — NOT open_positions
        self.alpha.reset_day()       # reset alpha buffers, re-warm up
        # DO NOT reset self.active_position — position held overnight carries forward
        self.daily_summary_sent = False
        self.last_date          = datetime.now().date()
        self.warmup()

        if self.active_position:
            log.info(f"Overnight position active | "
                     f"Type={self.active_position['type']} | "
                     f"Expiry={self.active_position['expiry']}")

    # ─── MAIN LOOP ────────────────────────────────────────────────────────

    def run(self):
        notifier.alert_startup(self.paper_mode)
        self.warmup()

        while True:
            try:
                # ── New trading day ────────────────────────────────────────
                if is_new_day(self.last_date):
                    self.new_day_reset()

                # ── Market closed — sleep, position holds overnight ────────
                if not is_market_open():
                    if self.active_position:
                        log.info(f"Market closed | Overnight position HELD | "
                                 f"Type={self.active_position['type']} "
                                 f"Expiry={self.active_position['expiry']}")
                    else:
                        log.info(f"Market closed ({now_time()}) — sleeping")
                    time.sleep(300)
                    continue

                # ── Expiry day: force exit before 14:30 ───────────────────
                if self.is_expiry_day():
                    self.handle_expiry_exit()

                # ── After TRADE_END: monitor existing position, no new entries
                if now_time() >= config.TRADE_END:
                    if not self.daily_summary_sent:
                        self.end_of_day()
                    # Still monitor open position even after TRADE_END
                    if self.active_position:
                        snap = self.fetch_and_update()
                        if snap:
                            self.monitor_position()
                    time.sleep(seconds_to_next_candle())
                    continue

                # ── Normal trading tick ────────────────────────────────────
                log.info(f"\n{'-'*50}\n  TICK @ {now_time()}\n{'-'*50}")

                snap = self.fetch_and_update()
                if snap:
                    if self.active_position:
                        self.monitor_position()   # check SL / target / signal exit
                    else:
                        self.check_and_enter(snap)  # look for new entry signal

                log.info(f"Risk status: {self.risk.status()}")

                sleep_secs = seconds_to_next_candle()
                log.info(f"Next tick in {sleep_secs}s\n")
                time.sleep(sleep_secs)

            except KeyboardInterrupt:
                log.info("Shutdown (Ctrl+C)")
                if self.active_position:
                    self.broker.exit_spread(self.active_position, "Manual shutdown")
                notifier.alert_shutdown("Manual (Ctrl+C)")
                break

            except Exception as e:
                msg = f"Unexpected error: {e}"
                log.error(msg, exc_info=True)
                notifier.alert_error(msg)
                time.sleep(60)


# ─── ENTRY POINT ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--paper", action="store_true",
                        help="Paper mode — real data, fake orders")
    args = parser.parse_args()

    algo = PremiaAlgo(paper_mode=args.paper)
    algo.run()
