# ═══════════════════════════════════════════════════════════════════════════
# trade_constructor.py — Build Credit Spread from Dhan Options Snapshot
# ═══════════════════════════════════════════════════════════════════════════

from datetime import datetime
from logger import get_logger
import config

log = get_logger("TradeConstructor")


class TradeConstructor:

    def __init__(self, data_feed):
        self.feed = data_feed

    # ─── PUT SPREAD (BULLISH) ─────────────────────────────────────────────

    def build_put_spread(self, spot: float, snap: dict, lots: int = None) -> dict:
        """
        BULLISH → Credit Put Spread
          SELL ATM Put  (collect premium)
          BUY  OTM Put  (400 pts lower — hedge)
        """
        n      = lots or config.NUM_LOTS
        atm    = snap["atm"]
        expiry = snap["expiry"]

        atm_pe = snap["pe"]       # ATM put  — sell this
        otm_pe = snap["otm_pe"]   # OTM put  — buy this (400 pts below)

        sell_price = atm_pe["bid"] if atm_pe["bid"] > 0 else atm_pe["ltp"]
        buy_price  = otm_pe["ask"] if otm_pe["ask"] > 0 else otm_pe["ltp"]

        net_credit = round(sell_price - buy_price, 2)
        max_loss   = round((config.SPREAD_WIDTH_POINTS - net_credit) * n * config.LOT_SIZE, 2)
        max_profit = round(net_credit * n * config.LOT_SIZE, 2)
        breakeven  = round(atm - net_credit, 2)

        spread = {
            "type"      : "PUT_SPREAD",
            "direction" : "BULLISH",
            "spot"      : spot,
            "expiry"    : expiry,
            "lots"      : n,
            "lot_size"  : config.LOT_SIZE,

            "sell_leg"  : {
                "action"     : "SELL",
                "security_id": atm_pe["security_id"],
                "strike"     : atm,
                "opt_type"   : "PE",
                "price"      : sell_price,
                "ltp"        : atm_pe["ltp"],
                "iv"         : atm_pe["iv"],
                "quantity"   : n * config.LOT_SIZE,
            },
            "buy_leg"   : {
                "action"     : "BUY",
                "security_id": otm_pe["security_id"],
                "strike"     : otm_pe["strike"],
                "opt_type"   : "PE",
                "price"      : buy_price,
                "ltp"        : otm_pe["ltp"],
                "iv"         : otm_pe["iv"],
                "quantity"   : n * config.LOT_SIZE,
            },

            "net_credit"          : net_credit,
            "max_profit"          : max_profit,
            "max_loss"            : max_loss,
            "breakeven"           : breakeven,
            "stop_loss_premium"   : round(sell_price * (1 + config.STOP_LOSS_PCT), 2),
            "entry_iv"            : round(snap.get("atm_vol", 0) / 2, 2),  # ATM IV at entry (for IV spike exit)
            "timestamp"           : datetime.now().isoformat(),
        }

        log.info(f"PUT SPREAD | Sell {atm}PE@{sell_price} Buy {otm_pe['strike']}PE@{buy_price} "
                 f"| Credit={net_credit} MaxLoss=₹{max_loss} BE={breakeven}")
        return spread

    # ─── CALL SPREAD (BEARISH) ────────────────────────────────────────────

    def build_call_spread(self, spot: float, snap: dict, lots: int = None) -> dict:
        """
        BEARISH → Credit Call Spread
          SELL ATM Call  (collect premium)
          BUY  OTM Call  (400 pts higher — hedge)
        """
        n      = lots or config.NUM_LOTS
        atm    = snap["atm"]
        expiry = snap["expiry"]

        atm_ce = snap["ce"]       # ATM call — sell this
        otm_ce = snap["otm_ce"]   # OTM call — buy this (400 pts above)

        sell_price = atm_ce["bid"] if atm_ce["bid"] > 0 else atm_ce["ltp"]
        buy_price  = otm_ce["ask"] if otm_ce["ask"] > 0 else otm_ce["ltp"]

        net_credit = round(sell_price - buy_price, 2)
        max_loss   = round((config.SPREAD_WIDTH_POINTS - net_credit) * n * config.LOT_SIZE, 2)
        max_profit = round(net_credit * n * config.LOT_SIZE, 2)
        breakeven  = round(atm + net_credit, 2)

        spread = {
            "type"      : "CALL_SPREAD",
            "direction" : "BEARISH",
            "spot"      : spot,
            "expiry"    : expiry,
            "lots"      : n,
            "lot_size"  : config.LOT_SIZE,

            "sell_leg"  : {
                "action"     : "SELL",
                "security_id": atm_ce["security_id"],
                "strike"     : atm,
                "opt_type"   : "CE",
                "price"      : sell_price,
                "ltp"        : atm_ce["ltp"],
                "iv"         : atm_ce["iv"],
                "quantity"   : n * config.LOT_SIZE,
            },
            "buy_leg"   : {
                "action"     : "BUY",
                "security_id": otm_ce["security_id"],
                "strike"     : otm_ce["strike"],
                "opt_type"   : "CE",
                "price"      : buy_price,
                "ltp"        : otm_ce["ltp"],
                "iv"         : otm_ce["iv"],
                "quantity"   : n * config.LOT_SIZE,
            },

            "net_credit"          : net_credit,
            "max_profit"          : max_profit,
            "max_loss"            : max_loss,
            "breakeven"           : breakeven,
            "stop_loss_premium"   : round(sell_price * (1 + config.STOP_LOSS_PCT), 2),
            "entry_iv"            : round(snap.get("atm_vol", 0) / 2, 2),  # ATM IV at entry (for IV spike exit)
            "timestamp"           : datetime.now().isoformat(),
        }

        log.info(f"CALL SPREAD | Sell {atm}CE@{sell_price} Buy {otm_ce['strike']}CE@{buy_price} "
                 f"| Credit={net_credit} MaxLoss=₹{max_loss} BE={breakeven}")
        return spread

    # ─── FROM SIGNAL ──────────────────────────────────────────────────────

    def build_from_signal(self, signal: dict, spot: float, snap: dict) -> dict | None:
        direction = signal.get("signal")
        if direction == "BULLISH":
            return self.build_put_spread(spot, snap)
        elif direction == "BEARISH":
            return self.build_call_spread(spot, snap)
        else:
            log.info("NEUTRAL signal — no spread built")
            return None

    # ─── SUMMARY PRINT ────────────────────────────────────────────────────

    def print_spread_summary(self, spread: dict):
        sell = spread["sell_leg"]
        buy  = spread["buy_leg"]
        print(f"\n{'='*52}")
        print(f"  {spread['type']}  |  {spread['direction']}  |  {spread['expiry']}")
        print(f"{'='*52}")
        print(f"  Spot     : {spread['spot']:.0f}    Lots: {spread['lots']}")
        print(f"  SELL     : {sell['strike']}{sell['opt_type']}  @ ₹{sell['price']:.2f}  IV={sell['iv']:.1f}%")
        print(f"  BUY      : {buy['strike']}{buy['opt_type']}  @ ₹{buy['price']:.2f}  IV={buy['iv']:.1f}%")
        print(f"  Credit   : ₹{spread['net_credit']:.2f} pts")
        print(f"  Max P    : ₹{spread['max_profit']:,.0f}")
        print(f"  Max L    : ₹{spread['max_loss']:,.0f}")
        print(f"  BE       : {spread['breakeven']:.0f}")
        print(f"  SL at    : ₹{spread['stop_loss_premium']:.2f} on sell leg")
        print(f"{'='*52}\n")
