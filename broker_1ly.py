# =============================================================================
# broker_1ly.py -- 1LY Options Webhook Broker
# =============================================================================
#
# How it works:
#   1. You create a Custom Strategy on 1LY platform (https://1lyalgos.inuvest.trade)
#   2. Define legs:
#        leg_1 -> SELL | CE | ATM   | Weekly  (sell leg)
#        leg_2 -> BUY  | CE | ATM+8 | Weekly  (buy hedge, 400 pts above)
#   3. Copy the webhook URL from 1LY and paste in config.py -> ONELY["webhook_url"]
#   4. This broker sends entry/exit signals to 1LY via webhook
#   5. 1LY auto-selects ATM at execution time and places orders on Alice Blue
#
# Webhook format (both legs sent at once — 1LY "All legs" format):
#   Entry:  {"signal": "entry", "legs": ["leg_1", "leg_2"]}
#   Exit:   {"signal": "exit",  "legs": ["leg_1", "leg_2"]}
# =============================================================================

import requests
from datetime import datetime
from logger import get_logger, log_trade
import config

log = get_logger("1LYBroker")


class OneLYBroker:
    """
    Sends entry/exit webhook signals to 1LY Options platform.
    1LY handles ATM selection, order routing, and execution on Alice Blue.
    """

    def __init__(self):
        self.webhook_url = config.ONELY["webhook_url"]
        self.leg_1       = config.ONELY["leg_1"]
        self.leg_2       = config.ONELY["leg_2"]
        self.connected   = True
        self._counter    = 2000

        if "PASTE" in self.webhook_url:
            log.warning("1LY webhook URL not configured! Paste URL in config.py -> ONELY['webhook_url']")
            self.connected = False
        else:
            log.info(f"1LY Broker ready | webhook configured | legs: {self.leg_1}, {self.leg_2}")

    def _send_signal(self, signal: str, legs: list) -> bool:
        """Send entry or exit signal to 1LY webhook."""
        if not self.connected:
            log.error("1LY webhook not configured")
            return False
        try:
            payload  = {"signal": signal, "legs": legs}
            response = requests.post(self.webhook_url, json=payload, timeout=10)
            if response.status_code == 200:
                log.info(f"1LY webhook OK | signal={signal} legs={legs} | response={response.text[:100]}")
                return True
            else:
                log.error(f"1LY webhook failed | status={response.status_code} | body={response.text[:200]}")
                return False
        except Exception as e:
            log.error(f"1LY webhook error: {e}")
            return False

    def place_spread(self, spread: dict) -> dict:
        """
        Send entry signal to 1LY — both legs at once.
        Format: {"signal": "entry", "legs": ["leg_1", "leg_2"]}
        """
        sell = spread["sell_leg"]
        buy  = spread["buy_leg"]

        log.info(f"1LY ENTRY | {spread['type']} | sending both legs at once...")
        success = self._send_signal("entry", [self.leg_1, self.leg_2])
        status  = "1LY_PLACED" if success else "1LY_FAIL"

        log.info(f"1LY ENTRY complete | status={status}")

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
            "status"      : status,
        })

        return {"status": status}

    def exit_spread(self, spread: dict, reason: str = "Exit") -> dict:
        """
        Send exit signal to 1LY — both legs at once.
        Format: {"signal": "exit", "legs": ["leg_1", "leg_2"]}
        """
        log.info(f"1LY EXIT | Reason: {reason} | sending both legs exit at once...")
        success = self._send_signal("exit", [self.leg_1, self.leg_2])
        status  = "1LY_EXITED" if success else "1LY_EXIT_FAIL"

        log.info(f"1LY EXIT complete | status={status}")

        log_trade({
            "date"       : datetime.now().strftime("%Y-%m-%d"),
            "time"       : datetime.now().strftime("%H:%M:%S"),
            "action"     : "EXIT",
            "type"       : spread.get("type", ""),
            "exit_reason": reason,
            "status"     : status,
        })

        return {"status": status, "reason": reason}

    def get_option_ltp(self, security_id: str) -> float:
        """
        1LY manages positions on Alice Blue side.
        We return 0 here -- P&L monitoring is done via 1LY dashboard.
        """
        return 0.0

    def get_positions(self) -> list:
        return []

    def get_client(self):
        return self
