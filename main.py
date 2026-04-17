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
from datetime import datetime, timezone, timedelta

import config
from logger            import get_logger
from broker_dhan       import DhanBroker, PaperBroker

# ─── IST TIMEZONE (GitHub Actions runs in UTC — must convert to IST) ───────
IST = timezone(timedelta(hours=5, minutes=30))
from broker_1ly        import OneLYBroker
from data_feed_dhan    import DhanDataFeed
from alpha_engine      import AlphaEngine
from trade_constructor import TradeConstructor
from risk_manager      import RiskManager
import notifier

log = get_logger("Main")


# ─── TIME HELPERS ─────────────────────────────────────────────────────────

def now_ist() -> datetime:
    """Always returns current time in IST — works on GitHub cloud (UTC) and local."""
    return datetime.now(IST)

def now_time() -> str:
    return now_ist().strftime("%H:%M")

def is_market_open() -> bool:
    t = now_time()
    return config.MARKET_OPEN <= t <= config.MARKET_CLOSE

def is_new_day(last_date) -> bool:
    return now_ist().date() != last_date

def seconds_to_next_candle() -> int:
    """Wait until next 5-minute boundary."""
    now  = now_ist()
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

        self.real_dhan = DhanBroker()

        if paper_mode:
            self.broker = PaperBroker()
        elif use_1ly:
            self.broker = OneLYBroker()
        else:
            self.broker = self.real_dhan

        self.feed    = DhanDataFeed(self.real_dhan.get_client())
        self.alpha   = AlphaEngine()
        self.builder = TradeConstructor(data_feed=self.feed)
        self.risk    = RiskManager()

        self.active_position    = None
        self.last_date          = now_ist().date()
        self.daily_summary_sent = False

    def warmup(self):
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

    def monitor_position(self) -> bool:
        pos  = self.active_position
        sell = pos["sell_leg"]
        buy  = pos["buy_leg"]

        current_sell = self.real_dhan.get_option_ltp(sell["security_id"])
        current_buy  = self.real_dhan.get_option_ltp(buy["security_id"])
        pnl          = self.risk.calculate_open_pnl(pos, current_sell, current_buy)

        sl_level = pos.get("stop_loss_premium", 0)
        log.info(f"Position | PnL=Rs.{pnl:+.0f} | "
                 f"Sell LTP={current_sell:.2f} (SL@{sl_level:.2f}) | "
                 f"Buy LTP={current_buy:.2f}")

        sl_hit, sl_reason = self.risk.check_stop_loss(pos, current_sell)
        if sl_hit:
            notifier.alert_stop_loss(pos, current_sell, pnl)
            self.broker.exit_spread(pos, reason=sl_reason)
            self.risk.record_trade_exit(pos, pnl, sl_reason)
            notifier.alert_trade_exit(pos, pnl, sl_reason)
            self.active_position = None
            return True

        ml_hit, ml_reason = self.risk.check_max_loss_breach(pos, pnl)
        if ml_hit:
            notifier.alert_stop_loss(pos, current_sell, pnl)
            self.broker.exit_spread(pos, reason=ml_reason)
            self.risk.record_trade_exit(pos, pnl, ml_reason)
            notifier.alert_trade_exit(pos, pnl, ml_reason)
            self.active_position = None
            return True

        pt_hit, pt_reason = self.risk.check_profit_target(pos, pnl)
        if pt_hit:
            self.broker.exit_spread(pos, reason=pt_reason)
            self.risk.record_trade_exit(pos, pnl, pt_reason)
            notifier.alert_trade_exit(pos, pnl, pt_reason)
            self.active_position = None
            return True

        current_signal = self.alpha.generate_signal()
        rev_hit, rev_reason = self.risk.check_signal_reversal(pos, current_signal["signal"])
        if rev_hit:
            self.broker.exit_spread(pos, reason=rev_reason)
            self.risk.record_trade_exit(pos, pnl, rev_reason)
            notifier.alert_trade_exit(pos, pnl, rev_reason)
            self.active_position = None
            return True

        return False

    def _entry_filters_pass(self, snap: dict, spread: dict) -> bool:
        sell_leg = spread["sell_leg"]

        if spread["net_credit"] < config.MIN_CREDIT_POINTS:
            log.info(f"SKIP | Net credit {spread['net_credit']} pts < min {config.MIN_CREDIT_POINTS} pts")
            return False

        atm_iv = snap.get("atm_vol", 0) / 2
        if atm_iv < config.MIN_ATM_IV:
            log.info(f"SKIP | ATM IV {atm_iv:.1f}% < min {config.MIN_ATM_IV}%")
            return False

        sell_oi = sell_leg.get("oi", 0)
        if sell_oi < config.MIN_ATM_OI:
            log.info(f"SKIP | Sell leg OI {sell_oi} < min {config.MIN_ATM_OI}")
            return False

        ltp = sell_leg.get("ltp", 0)
        bid = sell_leg.get("bid", 0)
        ask = sell_leg.get("ask", 0)
        if ltp > 0 and ask > 0 and bid > 0:
            ba_pct = (ask - bid) / ltp
            if ba_pct > config.MAX_BID_ASK_PCT:
                log.info(f"SKIP | Bid-ask {ba_pct*100:.1f}% > max {config.MAX_BID_ASK_PCT*100:.0f}%")
                return False

        log.info(f"Entry filters PASSED | credit={spread['net_credit']} | IV={atm_iv:.1f}% | OI={sell_oi}")
        return True

    def check_and_enter(self, snap: dict):
        can, reason = self.risk.can_trade()
        if not can:
            notifier.alert_no_trade(reason)
            return

        signal = self.alpha.generate_signal()
        if signal["signal"] == "NEUTRAL":
            log.info(f"NEUTRAL | a1={signal['alpha1']} a2={signal['alpha2']}")
            return

        spot = snap.get("spot", 0)
        notifier.alert_signal(signal, spot)

        spread = self.builder.build_from_signal(signal, spot, snap)
        if not spread:
            return

        if not self._entry_filters_pass(snap, spread):
            return

        lots           = self.risk.get_lot_size(spread)
        spread["lots"] = lots
        spread["sell_leg"]["quantity"] = lots * config.LOT_SIZE
        spread["buy_leg"]["quantity"]  = lots * config.LOT_SIZE

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

    def is_expiry_day(self) -> bool:
        """NIFTY weekly expiry is every Monday."""
        return now_ist().weekday() == 0

    def handle_expiry_exit(self):
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

    def end_of_day(self):
        if self.active_position and not self.daily_summary_sent:
            pos      = self.active_position
            sell_ltp = self.real_dhan.get_option_ltp(pos["sell_leg"]["security_id"])
            buy_ltp  = self.real_dhan.get_option_ltp(pos["buy_leg"]["security_id"])
            pnl      = self.risk.calculate_open_pnl(pos, sell_ltp, buy_ltp)
            log.info(f"EOD | Position HELD OVERNIGHT | Open PnL=Rs.{pnl:+.0f}")
            notifier.alert_daily_summary({**self.risk.status(), "open_pnl": pnl})
        elif not self.daily_summary_sent:
            notifier.alert_daily_summary(self.risk.status())
        self.daily_summary_sent = True

    def new_day_reset(self):
        log.info("New trading day — resetting daily counters")
        self.risk.reset_day()
        self.alpha.reset_day()
        self.daily_summary_sent = False
        self.last_date          = now_ist().date()
        self.warmup()

        if self.active_position:
            log.info(f"Overnight position active | "
                     f"Type={self.active_position['type']} | "
                     f"Expiry={self.active_position['expiry']}")

    def run(self):
        notifier.alert_startup(self.paper_mode)
        self.warmup()

        while True:
            try:
                if is_new_day(self.last_date):
                    self.new_day_reset()

                if not is_market_open():
                    if self.active_position:
                        log.info(f"Market closed | Overnight position HELD | "
                                 f"Type={self.active_position['type']} "
                                 f"Expiry={self.active_position['expiry']}")
                    else:
                        log.info(f"Market closed ({now_time()}) — sleeping")
                    time.sleep(300)
                    continue

                if self.is_expiry_day():
                    self.handle_expiry_exit()

                if now_time() >= config.TRADE_END:
                    if not self.daily_summary_sent:
                        self.end_of_day()
                    if self.active_position:
                        snap = self.fetch_and_update()
                        if snap:
                            self.monitor_position()
                    time.sleep(seconds_to_next_candle())
                    continue

                log.info(f"\n{'-'*50}\n  TICK @ {now_time()} IST\n{'-'*50}")

                snap = self.fetch_and_update()
                if snap:
                    if self.active_position:
                        self.monitor_position()
                    else:
                        self.check_and_enter(snap)

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
