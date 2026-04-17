# =============================================================================
# broker_1ly.py -- 1LY Options Webhook Broker
# =============================================================================
# Webhook format (both legs sent at once — 1LY "All legs" format):
#   Entry:  {"signal": "entry", "legs": ["leg_1", "leg_2"]}
#   Exit:   {"signal": "exit",  "legs": ["leg_1", "leg_2"]}
#
# BEARISH signal → CALL SPREAD → call_webhook_url
# BULLISH signal → PUT  SPREAD → put_webhook_url
# =============================================================================

import requests
from datetime import datetime
from logger import get_logger, log_trade
import config

log = get_logger("1LYBroker")


class OneLYBroker:

    def __init__(self):
        self.call_webhook_url = config.ONELY["call_webhook_url"]
        self.put_webhook_url  = config.ONELY["put_webhook_url"]
        self.leg_1            = config.ONELY["leg_1"]
        self.leg_2            = config.ONELY["leg_2"]
        self.connected        = True

        log.info(f"1LY Broker ready | CALL webhook configured | legs: {self.leg_1}, {self.leg_2}")
        log.info(f"1LY Broker ready | PUT  webhook configured | legs: {self.leg_1}, {self.leg_2}")

    def _send_signal(self, signal: str, legs: list, webhook_url: str) -> bool:
        try:
            payload  = {"signal": signal, "legs": legs}
            response = requests.post(webhook_url, json=payload, timeout=10)
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
        sell        = spread["sell_leg"]
        buy         = spread["buy_leg"]
        direction   = spread.get("direction", "")
        webhook_url = self.call_webhook_url if direction == "BEARISH" else self.put_webhook_url

        log.info(f"1LY ENTRY | {spread['type']} | {direction} | sending both legs...")
        success = self._send_signal("entry", [self.leg_1, self.leg_2], webhook_url)
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
        direction   = spread.get("direction", "")
        webhook_url = self.call_webhook_url if direction == "BEARISH" else self.put_webhook_url

        log.info(f"1LY EXIT | {direction} | Reason: {reason} | sending both legs exit...")
        success = self._send_signal("exit", [self.leg_1, self.leg_2], webhook_url)
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
        return 0.0

    def get_positions(self) -> list:
        return []

    def get_client(self):
        return self
