# ═══════════════════════════════════════════════════════════════════════════
# risk_manager.py — Position Sizing, Stop Loss, Daily Limits
# ═══════════════════════════════════════════════════════════════════════════

from datetime import datetime, timezone, timedelta
from logger import get_logger, log_pnl
import config
IST = timezone(timedelta(hours=5, minutes=30))

log = get_logger("RiskManager")


class RiskManager:

    def __init__(self):
        self.open_positions = []   # must exist before reset_day() references it
        self.reset_day()

    def reset_day(self):
        """
        Reset daily counters at start of each trading day.
        POSITIONAL mode: open_positions are KEPT — position carries overnight.
        """
        self.trades_today  = 0
        self.daily_pnl     = 0.0
        self.daily_pnl_pct = 0.0
        self.day_blocked   = False
        self.date = datetime.now(IST).date()
        # NOTE: open_positions is intentionally NOT reset here.
        # In positional strategy, existing spreads carry over to the next day.
        log.info(f"Risk manager reset for {self.date} | "
                 f"Carrying {len(self.open_positions)} open position(s) from previous day")

    # ─── PRE-TRADE CHECKS ─────────────────────────────────────────────────

    def can_trade(self) -> tuple[bool, str]:
        """
        Gate: returns (True, "") if allowed, (False, reason) if blocked.
        """
        if self.day_blocked:
            return False, "Daily loss limit hit — trading blocked for today"

        if self.trades_today >= config.MAX_TRADES_PER_DAY:
            return False, f"Max trades per day ({config.MAX_TRADES_PER_DAY}) reached"

        if len(self.open_positions) > 0:
            return False, "Already have an open position — wait for exit"

        if self.daily_pnl_pct <= -config.MAX_LOSS_PER_DAY:
            self.day_blocked = True
            return False, f"Daily loss limit {config.MAX_LOSS_PER_DAY*100:.1f}% breached"

        now = datetime.now(IST).strftime("%H:%M")
        if now < config.TRADE_START:
            return False, f"Too early — trading starts at {config.TRADE_START}"
        if now > config.TRADE_END:
            return False, f"Too late — no new trades after {config.TRADE_END}"

        return True, ""

    # ─── POSITION SIZING ──────────────────────────────────────────────────

    def get_lot_size(self, spread: dict) -> int:
        """
        Calculate number of lots based on max risk per trade.
        Max risk per lot = spread max_loss / num_lots (from constructor)
        """
        max_risk_inr    = config.CAPITAL * config.MAX_RISK_PER_TRADE
        loss_per_lot    = (config.SPREAD_WIDTH_POINTS - spread["net_credit"]) * config.LOT_SIZE

        if loss_per_lot <= 0:
            log.warning("Net credit >= spread width — unusual, defaulting to 1 lot")
            return 1

        lots = int(max_risk_inr / loss_per_lot)
        lots = max(1, lots)   # minimum 1 lot

        log.info(f"Position sizing: max_risk=₹{max_risk_inr:.0f} | "
                 f"loss_per_lot=₹{loss_per_lot:.0f} | lots={lots}")
        return lots

    # ─── STOP LOSS CHECK ──────────────────────────────────────────────────

    def check_stop_loss(self, position: dict, current_sell_premium: float) -> tuple[bool, str]:
        """
        Check if the sold leg premium has risen above stop loss level.
        Stop loss = sell premium increases by STOP_LOSS_PCT (e.g. 50%).

        Args:
          position           : spread dict from trade constructor
          current_sell_premium: current market price of sell leg

        Returns (True, reason) if stop loss hit, else (False, "")
        """
        sl_level = position["stop_loss_premium"]

        if current_sell_premium >= sl_level:
            reason = (f"STOP LOSS HIT | Sell leg premium {current_sell_premium:.2f} "
                      f">= SL level {sl_level:.2f}")
            log.warning(reason)
            return True, reason

        return False, ""

    def check_max_loss_breach(self, position: dict, current_pnl: float) -> tuple[bool, str]:
        """
        Check if current P&L on open position exceeds max loss.
        """
        if current_pnl <= -position["max_loss"]:
            reason = f"MAX LOSS BREACHED | PnL Rs.{current_pnl:.2f} | Max loss Rs.{position['max_loss']:.2f}"
            log.warning(reason)
            return True, reason
        return False, ""

    def check_profit_target(self, position: dict, current_pnl: float) -> tuple[bool, str]:
        """
        Exit when profit reaches PROFIT_TARGET_PCT of max possible profit.
        ZEN Rule: Lock in gains at 50% of max profit — don't be greedy.

        Example: Max profit = Rs.10,950 → exit when PnL >= Rs.5,475
        """
        target_pnl = position["max_profit"] * config.PROFIT_TARGET_PCT
        if current_pnl >= target_pnl:
            reason = (f"PROFIT TARGET HIT | PnL Rs.{current_pnl:.0f} "
                      f">= target Rs.{target_pnl:.0f} "
                      f"({config.PROFIT_TARGET_PCT*100:.0f}% of max profit)")
            log.info(reason)
            return True, reason
        return False, ""

    def check_signal_reversal(self, position: dict, current_signal: str) -> tuple[bool, str]:
        """
        Exit if the alpha signal reverses against our position.
        ZEN Rule: Don't hold a bearish spread if market turns bullish (and vice versa).

        CALL_SPREAD (BEARISH position) → exit if signal turns BULLISH
        PUT_SPREAD  (BULLISH position) → exit if signal turns BEARISH
        """
        if not config.SIGNAL_EXIT:
            return False, ""

        pos_type = position.get("direction", "")

        if pos_type == "BEARISH" and current_signal == "BULLISH":
            reason = "SIGNAL REVERSAL | Market turned BULLISH — exiting CALL SPREAD early"
            log.warning(reason)
            return True, reason

        if pos_type == "BULLISH" and current_signal == "BEARISH":
            reason = "SIGNAL REVERSAL | Market turned BEARISH — exiting PUT SPREAD early"
            log.warning(reason)
            return True, reason

        return False, ""

    # ─── P&L TRACKING ─────────────────────────────────────────────────────

    def calculate_open_pnl(self, position: dict,
                            current_sell_price: float,
                            current_buy_price:  float) -> float:
        """
        P&L of an open spread position.
        Credit spread P&L = (entry_credit - current_spread_value) × qty
        """
        entry_credit   = position["net_credit"]
        current_spread = current_sell_price - current_buy_price
        pnl_per_lot    = (entry_credit - current_spread) * config.LOT_SIZE
        total_pnl      = pnl_per_lot * position["lots"]

        log.debug(f"Open PnL: entry_credit={entry_credit} current_spread={current_spread:.2f} "
                  f"pnl_per_lot={pnl_per_lot:.2f} total=₹{total_pnl:.2f}")
        return round(total_pnl, 2)

    def record_trade_exit(self, position: dict, exit_pnl: float, exit_reason: str):
        """Update daily counters after closing a trade."""
        self.daily_pnl     += exit_pnl
        self.daily_pnl_pct  = self.daily_pnl / config.CAPITAL

        if position in self.open_positions:
            self.open_positions.remove(position)

        log.info(f"Trade closed | PnL: ₹{exit_pnl:.2f} | Reason: {exit_reason} | "
                 f"Daily PnL: ₹{self.daily_pnl:.2f} ({self.daily_pnl_pct*100:.2f}%)")

        log_pnl({
            "date"         : datetime.now().strftime("%Y-%m-%d"),
            "time"         : datetime.now().strftime("%H:%M:%S"),
            "type"         : position["type"],
            "direction"    : position["direction"],
            "net_credit"   : position["net_credit"],
            "exit_pnl"     : exit_pnl,
            "daily_pnl"    : round(self.daily_pnl, 2),
            "daily_pnl_pct": round(self.daily_pnl_pct * 100, 3),
            "exit_reason"  : exit_reason,
        })

    def register_open_position(self, position: dict):
        """Register a new open position."""
        self.open_positions.append(position)
        self.trades_today += 1
        log.info(f"Position registered | Trade #{self.trades_today} today | "
                 f"Type: {position['type']} | Credit: {position['net_credit']}")

    # ─── STATUS ───────────────────────────────────────────────────────────

    def status(self) -> dict:
        return {
            "date"           : str(self.date),
            "trades_today"   : self.trades_today,
            "open_positions" : len(self.open_positions),
            "daily_pnl"      : round(self.daily_pnl, 2),
            "daily_pnl_pct"  : round(self.daily_pnl_pct * 100, 3),
            "day_blocked"    : self.day_blocked,
        }
