# ═══════════════════════════════════════════════════════════════════════════
# broker_dhan.py — Dhan HQ Order Placement + Paper Mode
# ═══════════════════════════════════════════════════════════════════════════

import time
from datetime import datetime
from logger import get_logger, log_trade
import config

log = get_logger("DhanBroker")


class DhanBroker:
    """
    Wraps dhanhq client for options order placement.
    Handles both SELL and BUY legs of credit spreads.
    Dhan access token is valid 30 days — no daily refresh needed.
    """

    def __init__(self):
        self.dhan      = None
        self.connected = False
        self._connect()

    def _connect(self):
        try:
            from dhanhq import dhanhq
            self.dhan = dhanhq(
                client_id    = config.DHAN["client_id"],
                access_token = config.DHAN["access_token"],
            )
            self.connected = True
            log.info("Dhan HQ connected successfully")
        except ImportError:
            log.error("dhanhq not installed. Run: pip install dhanhq")
        except Exception as e:
            log.error(f"Dhan connection error: {e}")

    def get_client(self):
        return self.dhan

    # ─── SINGLE LEG ORDER ─────────────────────────────────────────────────

    def place_order(self, security_id: str, action: str,
                    quantity: int, tag: str = "PREMIA") -> str | None:
        """
        Place a single options order at market price.

        Args:
          security_id : Dhan security_id of the option
          action      : "BUY" or "SELL"
          quantity    : number of units (lots × lot_size)
          tag         : order tag

        Returns order_id string or None on failure.
        """
        if not self.connected:
            log.error("Dhan not connected")
            return None

        try:
            transaction = (
                self.dhan.BUY  if action == "BUY"
                else self.dhan.SELL
            )

            resp = self.dhan.place_order(
                security_id      = security_id,
                exchange_segment = config.NFO_SEGMENT,
                transaction_type = transaction,
                quantity         = quantity,
                order_type       = self.dhan.MARKET,
                product_type     = self.dhan.CARRYFORWARD,  # overnight hold
                price            = 0,
            )

            order_id = str(resp.get("data", {}).get("orderId", ""))
            status   = resp.get("status", "")

            if order_id and status == "success":
                log.info(f"Order OK: {action} {quantity} secId={security_id} | ID={order_id}")
                return order_id
            else:
                log.error(f"Order failed: {resp}")
                return None

        except Exception as e:
            log.error(f"place_order error ({action} {security_id}): {e}")
            return None

    # ─── SPREAD ENTRY ─────────────────────────────────────────────────────

    def place_spread(self, spread: dict) -> dict:
        """
        Place both legs of a credit spread.
        SELL leg first (credit), then BUY leg (hedge).
        """
        sell = spread["sell_leg"]
        buy  = spread["buy_leg"]

        log.info(f"Entering {spread['type']} | "
                 f"Sell {sell['strike']}{sell['opt_type']} "
                 f"Buy {buy['strike']}{buy['opt_type']}")

        sell_id = self.place_order(
            security_id = sell["security_id"],
            action      = "SELL",
            quantity    = sell["quantity"],
            tag         = f"PREMIA_{spread['type']}_SELL",
        )

        time.sleep(0.5)   # small gap between legs

        buy_id = self.place_order(
            security_id = buy["security_id"],
            action      = "BUY",
            quantity    = buy["quantity"],
            tag         = f"PREMIA_{spread['type']}_BUY",
        )

        status = "PLACED" if (sell_id and buy_id) else "PARTIAL_FAIL"

        log_trade({
            "date"         : datetime.now().strftime("%Y-%m-%d"),
            "time"         : datetime.now().strftime("%H:%M:%S"),
            "action"       : "ENTRY",
            "type"         : spread["type"],
            "sell_symbol"  : f"{sell['strike']}{sell['opt_type']}",
            "sell_sec_id"  : sell["security_id"],
            "sell_price"   : sell["price"],
            "buy_symbol"   : f"{buy['strike']}{buy['opt_type']}",
            "buy_sec_id"   : buy["security_id"],
            "buy_price"    : buy["price"],
            "net_credit"   : spread["net_credit"],
            "max_profit"   : spread["max_profit"],
            "max_loss"     : spread["max_loss"],
            "sell_order_id": sell_id,
            "buy_order_id" : buy_id,
            "status"       : status,
        })

        log.info(f"Spread {status} | Sell ID: {sell_id} | Buy ID: {buy_id}")
        return {"sell_order_id": sell_id, "buy_order_id": buy_id, "status": status}

    # ─── SPREAD EXIT ──────────────────────────────────────────────────────

    def exit_spread(self, spread: dict, reason: str = "Exit") -> dict:
        """Reverse both legs to close the spread."""
        sell = spread["sell_leg"]
        buy  = spread["buy_leg"]

        log.info(f"Exiting {spread['type']} | Reason: {reason}")

        # Buy back the sold leg
        exit_sell_id = self.place_order(
            security_id = sell["security_id"],
            action      = "BUY",
            quantity    = sell["quantity"],
            tag         = "PREMIA_EXIT_SELL",
        )

        time.sleep(0.5)

        # Sell the bought leg
        exit_buy_id = self.place_order(
            security_id = buy["security_id"],
            action      = "SELL",
            quantity    = buy["quantity"],
            tag         = "PREMIA_EXIT_BUY",
        )

        status = "EXITED" if (exit_sell_id and exit_buy_id) else "EXIT_FAIL"

        log_trade({
            "date"          : datetime.now().strftime("%Y-%m-%d"),
            "time"          : datetime.now().strftime("%H:%M:%S"),
            "action"        : "EXIT",
            "type"          : spread["type"],
            "sell_symbol"   : f"{sell['strike']}{sell['opt_type']}",
            "buy_symbol"    : f"{buy['strike']}{buy['opt_type']}",
            "exit_reason"   : reason,
            "exit_sell_id"  : exit_sell_id,
            "exit_buy_id"   : exit_buy_id,
            "status"        : status,
        })

        log.info(f"Exit {status} | Reason: {reason}")
        return {"status": status, "reason": reason}

    # ─── LIVE OPTION LTP ──────────────────────────────────────────────────

    def get_option_ltp(self, security_id: str) -> float:
        """Fetch current LTP of an option by security_id via direct API call."""
        try:
            import requests
            headers = {
                "access-token": config.DHAN["access_token"],
                "client-id"   : config.DHAN["client_id"],
                "Content-Type": "application/json",
            }
            resp = requests.post(
                "https://api.dhan.co/v2/marketfeed/ltp",
                json={config.NFO_SEGMENT: [str(security_id)]},
                headers=headers,
                timeout=10,
            )
            data = resp.json().get("data", {}).get(config.NFO_SEGMENT, {})
            item = data.get(str(security_id), {})
            ltp  = float(item.get("last_price") or item.get("LTP") or 0)
            return ltp
        except Exception as e:
            log.error(f"get_option_ltp error (secId={security_id}): {e}")
            return 0.0

    def get_positions(self) -> list:
        """Return current open positions from Dhan."""
        try:
            resp = self.dhan.get_positions()
            return resp.get("data", [])
        except Exception as e:
            log.error(f"get_positions error: {e}")
            return []

    def get_order_status(self, order_id: str) -> str:
        """Return status string for a given order ID."""
        try:
            orders = self.dhan.get_order_list().get("data", [])
            for o in orders:
                if str(o.get("orderId")) == str(order_id):
                    return o.get("orderStatus", "UNKNOWN")
            return "NOT_FOUND"
        except Exception as e:
            log.error(f"get_order_status error: {e}")
            return "ERROR"


# ─── PAPER BROKER ─────────────────────────────────────────────────────────

class PaperBroker:
    """
    Simulates all orders without placing anything real.
    Use for testing before going live.
    """

    def __init__(self):
        self.connected = True
        self._counter  = 1000
        log.info("PAPER MODE — no real orders will be placed")

    def get_client(self):
        return self

    def place_order(self, security_id, action, quantity, tag="PAPER"):
        oid = f"PAPER_{self._counter}"
        self._counter += 1
        log.info(f"[PAPER] {action} qty={quantity} secId={security_id} | ID={oid}")
        return oid

    def place_spread(self, spread):
        sell = spread["sell_leg"]
        buy  = spread["buy_leg"]
        sid  = self.place_order(sell["security_id"], "SELL", sell["quantity"])
        bid  = self.place_order(buy["security_id"],  "BUY",  buy["quantity"])
        log_trade({
            "date"        : datetime.now().strftime("%Y-%m-%d"),
            "time"        : datetime.now().strftime("%H:%M:%S"),
            "action"      : "ENTRY",
            "type"        : spread["type"],
            "sell_symbol" : f"{sell['strike']}{sell['opt_type']}",
            "sell_price"  : sell["price"],
            "buy_symbol"  : f"{buy['strike']}{buy['opt_type']}",
            "buy_price"   : buy["price"],
            "net_credit"  : spread["net_credit"],
            "max_profit"  : spread["max_profit"],
            "max_loss"    : spread["max_loss"],
            "status"      : "PAPER",
        })
        return {"sell_order_id": sid, "buy_order_id": bid, "status": "PAPER_PLACED"}

    def exit_spread(self, spread, reason="Paper Exit"):
        sell = spread["sell_leg"]
        buy  = spread["buy_leg"]
        self.place_order(sell["security_id"], "BUY",  sell["quantity"])
        self.place_order(buy["security_id"],  "SELL", buy["quantity"])
        return {"status": "PAPER_EXITED", "reason": reason}

    def get_option_ltp(self, security_id):
        return 0.0

    def get_positions(self):
        return []

    # Mock Dhan API methods used by data feed
    def get_market_feed(self, req):           return {"data": {}}
    def historical_minute_data(self, **kw):   return {"data": {}}
    def get_option_chain(self, **kw):         return {"data": {}}


def get_broker(paper_mode: bool = False):
    """Factory — returns live Dhan broker or paper broker."""
    if paper_mode or config.PAPER_MODE:
        return PaperBroker()
    return DhanBroker()
