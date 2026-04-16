# ═══════════════════════════════════════════════════════════════════════════
# logger.py — Logging + Trade Record Keeping
# ═══════════════════════════════════════════════════════════════════════════

import logging
import os
import csv
from datetime import datetime
import config

os.makedirs(config.LOG_DIR,           exist_ok=True)
os.makedirs(os.path.dirname(config.TRADE_LOG), exist_ok=True)

def get_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    level = getattr(logging, config.LOG_LEVEL, logging.INFO)
    logger.setLevel(level)

    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    # Console handler
    ch = logging.StreamHandler()
    ch.setFormatter(fmt)
    logger.addHandler(ch)

    # File handler (daily rotating)
    today     = datetime.now().strftime("%Y-%m-%d")
    log_file  = os.path.join(config.LOG_DIR, f"premia_{today}.log")
    fh        = logging.FileHandler(log_file)
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    return logger


def log_trade(trade: dict):
    """Append a trade record to the CSV trade log."""
    file_exists = os.path.isfile(config.TRADE_LOG)
    with open(config.TRADE_LOG, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=trade.keys())
        if not file_exists:
            writer.writeheader()
        writer.writerow(trade)


def log_pnl(pnl: dict):
    """Append a daily P&L record."""
    file_exists = os.path.isfile(config.PNL_LOG)
    with open(config.PNL_LOG, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=pnl.keys())
        if not file_exists:
            writer.writeheader()
        writer.writerow(pnl)
