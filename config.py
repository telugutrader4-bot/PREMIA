# config.py — PREMIA | Secrets loaded from environment variables (GitHub Actions)
import os

# ── DHAN API ──────────────────────────────────────────────────────────────
DHAN = {
    "client_id"   : os.environ.get("DHAN_CLIENT_ID",    "1100484167"),
    "access_token": os.environ.get("DHAN_ACCESS_TOKEN", ""),
}

# ── 1LY OPTIONS WEBHOOK ───────────────────────────────────────────────────
ONELY = {
    "enabled"    : True,
    "webhook_url": os.environ.get("ONELY_WEBHOOK_URL", "https://api.1lyalgos.com/v3/webhook/tradingview/b11ea088-bd8c-49f9-b819-fd8d75204e401776330085"),
    "leg_1"      : "leg_1",
    "leg_2"      : "leg_2",
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
# ZEN Credit Spread Overnight — pin-to-pin parameters (Stratzy/DhanHQ)
ALPHA1_LOOKBACK  = 800
ALPHA2_LOOKBACK  = 300
BULL_THRESHOLD   = 0.70   # loosened from 0.80 → more entries (~3 trades/week like ZEN)
BEAR_THRESHOLD   = 0.30   # loosened from 0.20 → more entries (~3 trades/week like ZEN)

# ── STRATEGY TYPE ─────────────────────────────────────────────────────────
POSITIONAL   = True    # True  = overnight hold (position carries to next day)
                       # False = intraday only  (force exit same day)

# ── TRADING HOURS (IST) ───────────────────────────────────────────────────
MARKET_OPEN       = "09:15"
TRADE_START       = "09:30"   # ZEN enters early — 9:30 AM after open settles
TRADE_END         = "14:00"   # no new entries after this (position stays open overnight)
MARKET_CLOSE      = "15:30"
EXPIRY_EXIT_TIME  = "14:30"   # on expiry day, force-close position before this time
SIGNAL_CHECK_MINS = 5

# ── RISK ──────────────────────────────────────────────────────────────────
CAPITAL            = 200000
MAX_RISK_PER_TRADE = 0.05
STOP_LOSS_PCT      = 0.50       # SL fires when sell leg rises 50% above entry
MAX_TRADES_PER_DAY = 1          # ZEN = 1 active position at a time (positional)
MAX_LOSS_PER_DAY   = 0.05       # 5% daily loss cap (ZEN avg loss = -4.42%)
PAPER_MODE         = True       # <-- keep True for testing!

# ── ENTRY FILTERS (ZEN Credit Spread rules — pin to pin) ──────────────────
MIN_CREDIT_POINTS  = 20         # ZEN takes lower credit too — reduced from 30
MIN_ATM_IV         = 10.0       # skip if ATM IV < 10% (not worth selling)
MIN_ATM_OI         = 500        # skip if ATM OI < 500 (illiquid strike)
MAX_BID_ASK_PCT    = 0.25       # ZEN tolerates slightly wider spread — raised from 0.20

# ── EXIT CONDITIONS (ZEN Credit Spread rules — pin to pin) ────────────────
PROFIT_TARGET_PCT  = 0.50       # exit when profit = 50% of max profit (lock gains)
SIGNAL_EXIT        = True       # exit if signal reverses to opposite direction

# ── LOGGING ───────────────────────────────────────────────────────────────
LOG_DIR   = "logs"
TRADE_LOG = "trades/premia_trade_log.csv"
PNL_LOG   = "trades/premia_pnl_log.csv"
LOG_LEVEL = "INFO"
