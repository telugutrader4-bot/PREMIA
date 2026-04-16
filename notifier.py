# ═══════════════════════════════════════════════════════════════════════════
# notifier.py — Telegram Alerts for Every Trade Event
# ═══════════════════════════════════════════════════════════════════════════
#
#  Sends instant Telegram messages for:
#    - Trade entry (spread details, entry/SL/target)
#    - Stop loss hit
#    - Trade exit + P&L
#    - Daily summary
#    - Errors / warnings
#    - Algo start / shutdown
#
# ═══════════════════════════════════════════════════════════════════════════

import requests
from datetime import datetime
from logger import get_logger
import config

log = get_logger("Notifier")

TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"


def _send(text: str, parse_mode: str = "HTML") -> bool:
    """Low-level Telegram message sender."""
    if not config.TELEGRAM.get("enabled"):
        return True

    token   = config.TELEGRAM["bot_token"]
    chat_id = config.TELEGRAM["chat_id"]

    if not token or token == "YOUR_BOT_TOKEN":
        log.debug("Telegram not configured — skipping notification")
        return False

    try:
        url  = TELEGRAM_API.format(token=token)
        resp = requests.post(url, json={
            "chat_id"   : chat_id,
            "text"      : text,
            "parse_mode": parse_mode,
        }, timeout=10)

        if resp.status_code == 200:
            return True
        else:
            log.warning(f"Telegram error {resp.status_code}: {resp.text}")
            return False

    except Exception as e:
        log.error(f"Telegram send failed: {e}")
        return False


# ─── ALERT FUNCTIONS ──────────────────────────────────────────────────────

def alert_startup(paper_mode: bool = False):
    mode = "📄 PAPER MODE" if paper_mode else "🟢 LIVE MODE"
    _send(
        f"<b>🤖 PREMIA — Started</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"Mode     : {mode}\n"
        f"Capital  : ₹{config.CAPITAL:,}\n"
        f"Max lots : {config.NUM_LOTS}\n"
        f"Time     : {datetime.now().strftime('%d %b %Y %H:%M IST')}\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"Watching NIFTY every {config.SIGNAL_CHECK_MINS} min ⏱"
    )


def alert_shutdown(reason: str = "Manual"):
    _send(
        f"<b>🔴 PREMIA — Stopped</b>\n"
        f"Reason: {reason}\n"
        f"Time  : {datetime.now().strftime('%H:%M IST')}"
    )


def alert_signal(signal: dict, spot: float):
    emoji = "📈" if signal["signal"] == "BULLISH" else "📉"
    _send(
        f"<b>{emoji} Signal Detected</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"Direction : <b>{signal['signal']}</b>\n"
        f"NIFTY     : {spot:.2f}\n"
        f"Alpha 1   : {signal['alpha1']}\n"
        f"Alpha 2   : {signal['alpha2']}\n"
        f"Strength  : {signal['strength']}\n"
        f"Time      : {datetime.now().strftime('%H:%M IST')}"
    )


def alert_trade_entry(spread: dict):
    sell = spread["sell_leg"]
    buy  = spread["buy_leg"]
    emoji = "🟢" if spread["direction"] == "BULLISH" else "🔴"

    _send(
        f"<b>{emoji} Trade Entered — {spread['type']}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"NIFTY Spot  : {spread['spot']:.0f}\n"
        f"Expiry      : {spread['expiry']}\n"
        f"Lots        : {spread['lots']}\n\n"
        f"<b>SELL</b> {sell['strike']}{sell['opt_type']} @ ₹{sell['price']:.2f}\n"
        f"<b>BUY </b> {buy['strike']}{buy['opt_type']} @ ₹{buy['price']:.2f}\n\n"
        f"Net Credit  : ₹{spread['net_credit']:.2f} pts\n"
        f"Max Profit  : ₹{spread['max_profit']:,.0f}\n"
        f"Max Loss    : ₹{spread['max_loss']:,.0f}\n"
        f"Breakeven   : {spread['breakeven']:.0f}\n"
        f"SL Level    : {spread['stop_loss_premium']:.2f} on sell leg\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"🕐 {datetime.now().strftime('%H:%M IST')}"
    )


def alert_stop_loss(spread: dict, current_sell: float, pnl: float):
    _send(
        f"<b>🚨 STOP LOSS HIT</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"Type        : {spread['type']}\n"
        f"Sell Strike : {spread['sell_leg']['strike']}{spread['sell_leg']['opt_type']}\n"
        f"Entry Price : ₹{spread['sell_leg']['price']:.2f}\n"
        f"Current LTP : ₹{current_sell:.2f}\n"
        f"SL Level    : ₹{spread['stop_loss_premium']:.2f}\n"
        f"P&L         : ₹{pnl:,.0f}\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"Exiting position now..."
    )


def alert_trade_exit(spread: dict, pnl: float, reason: str):
    emoji = "✅" if pnl >= 0 else "❌"
    _send(
        f"<b>{emoji} Trade Closed</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"Type    : {spread['type']}\n"
        f"Reason  : {reason}\n"
        f"P&L     : <b>₹{pnl:+,.0f}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"🕐 {datetime.now().strftime('%H:%M IST')}"
    )


def alert_daily_summary(risk_status: dict):
    pnl     = risk_status["daily_pnl"]
    pnl_pct = risk_status["daily_pnl_pct"]
    trades  = risk_status["trades_today"]
    emoji   = "📊✅" if pnl >= 0 else "📊❌"

    _send(
        f"<b>{emoji} Daily Summary</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"Date        : {risk_status['date']}\n"
        f"Trades      : {trades}\n"
        f"Daily P&L   : <b>₹{pnl:+,.0f} ({pnl_pct:+.2f}%)</b>\n"
        f"Capital     : ₹{config.CAPITAL:,}\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"See trades/pnl_log.csv for details"
    )


def alert_error(message: str):
    _send(
        f"<b>⚠️ Algo Error</b>\n"
        f"{message}\n"
        f"🕐 {datetime.now().strftime('%H:%M IST')}"
    )


def alert_no_trade(reason: str):
    """Silent — only logs, no Telegram (avoid spam)."""
    log.info(f"No trade: {reason}")
