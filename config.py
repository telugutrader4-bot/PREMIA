# config.py — PREMIA | Secrets loaded from environment variables (GitHub Actions)
import os

# ── DHAN API ──────────────────────────────────────────────────────────────
DHAN = {
    "client_id"   : os.environ.get("DHAN_CLIENT_ID",    "1100484167"),
    "access_token": os.environ.get("DHAN_ACCESS_TOKEN", ""),
}

# ── 1LY OPTIONS WEBHOOK ───────────────────────────────────────────────────
ONELY = {
    "enabled"          : True,
    # BEARISH signal → CALL SPREAD (Sell ATM CE + Buy OTM CE)
    "call_webhook_url" : os.environ.get("ONELY_CALL_WEBHOOK_URL", "https://api.1lyalgos.com/v3/webhook/tradingview/b11ea088-bd8c-49f9-b819-fd8d75204e401776330085"),
    # BULLISH signal → PUT SPREAD (Sell ATM PE + Buy OTM PE)
    "put_webhook_url"  : os.environ.get("ONELY_PUT_WEBHOOK_URL",  "https://api.1lyalgos.com/v3/webhook/tradingview/ec700d06-ce2c-40bb-a4e6-10fe029bf5b41776408474"),
    "leg_1"            : "leg_1",
    "leg_2"            : "leg_2",
}

# ── TELEGRAM ──────────────────────────────────────────────────────────────
TELEGRAM = {
    "bot_token": os.environ.get("TELEGRAM_BOT_TOKEN", "8393682904:AAHcCLhcob70KKHCztJLpAQLD3eWUe_FylE"),
    "chat_id"  : os.environ.get("TELEGRAM_CHAT_ID",   "391958100"),
    "enabled"  : True,
}

# ── INSTRUMENT ────────────────────────────────────────────────────────────
NIFTY_SECURITY_ID   = "13"
NIFTY_INDEX_SEGMENT = "IDX_I"
NFO_SEGMENT         = "NSE_FNO"
LOT_SIZE            = 75
NUM_LOTS            = 1
STRIKE_STEP         = 50
SPREAD_WIDTH_POINTS = 400

# ── STRATEGY ──────────────────────────────────────────────────────────────
ALPHA1_LOOKBACK  = 800
ALPHA2_LOOKBACK  = 300
BULL_THRESHOLD   = 0.70
BEAR_THRESHOLD   = 0.30

# ── STRATEGY TYPE ─────────────────────────────────────────────────────────
POSITIONAL   = True

# ── TRADING HOURS (IST) ───────────────────────────────────────────────────
MARKET_OPEN       = "09:15"
TRADE_START       = "09:30"
TRADE_END         = "14:00"
MARKET_CLOSE      = "15:30"
EXPIRY_EXIT_TIME  = "14:30"
SIGNAL_CHECK_MINS = 5

# ── RISK ──────────────────────────────────────────────────────────────────
CAPITAL            = 200000
MAX_RISK_PER_TRADE = 0.05
STOP_LOSS_PCT      = 0.50
MAX_TRADES_PER_DAY = 1
MAX_LOSS_PER_DAY   = 0.05
PAPER_MODE         = False

# ── ENTRY FILTERS ─────────────────────────────────────────────────────────
MIN_CREDIT_POINTS  = 20
MIN_ATM_IV         = 10.0
MIN_ATM_OI         = 0
MAX_BID_ASK_PCT    = 0.25

# ── EXIT CONDITIONS ───────────────────────────────────────────────────────
PROFIT_TARGET_PCT  = 0.50
SIGNAL_EXIT        = True

# ── LOGGING ───────────────────────────────────────────────────────────────
LOG_DIR   = "logs"
TRADE_LOG = "trades/premia_trade_log.csv"
PNL_LOG   = "trades/premia_pnl_log.csv"
LOG_LEVEL = "INFO"
