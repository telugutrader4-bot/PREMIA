#!/usr/bin/env python3
# ═══════════════════════════════════════════════════════════════════════════
# test_connection.py — Pre-flight Check Before Live Trading
#
# Run this BEFORE main.py to verify everything is working.
# All 7 checks must pass before you run the algo tomorrow.
#
# Usage:  python test_connection.py
# ═══════════════════════════════════════════════════════════════════════════

import sys
import time
from datetime import datetime

print("\n" + "═"*55)
print("  PREMIA — Pre-flight Connection Test")
print("═"*55)

passed = 0
failed = 0

def check(name, fn):
    global passed, failed
    print(f"\n[{'─'*50}]")
    print(f"  Testing: {name}")
    try:
        result = fn()
        if result:
            print(f"  ✅ PASS — {result}")
            passed += 1
        else:
            print(f"  ❌ FAIL — returned empty/None")
            failed += 1
    except Exception as e:
        print(f"  ❌ FAIL — {e}")
        failed += 1


# ─── CHECK 1: Config loaded ────────────────────────────────────────────────
def test_config():
    import config
    issues = []
    if "YOUR" in config.DHAN["client_id"]:
        issues.append("Dhan client_id not set")
    if "YOUR" in config.DHAN["access_token"]:
        issues.append("Dhan access_token not set")
    if issues:
        raise Exception(", ".join(issues))
    return f"client_id={config.DHAN['client_id'][:6]}... OK"

check("Config.py (API keys filled in)", test_config)


# ─── CHECK 2: dhanhq package installed ────────────────────────────────────
def test_dhanhq():
    from dhanhq import dhanhq
    return "dhanhq package installed"

check("dhanhq Python package", test_dhanhq)


# ─── CHECK 3: Dhan API connection ─────────────────────────────────────────
def test_dhan_connect():
    import config
    from dhanhq import dhanhq
    dhan = dhanhq(
        client_id    = config.DHAN["client_id"],
        access_token = config.DHAN["access_token"],
    )
    # Try fetching fund limits as a connectivity test
    resp = dhan.get_fund_limits()
    if resp.get("status") == "success":
        data        = resp.get("data", {})
        available   = data.get("availabelBalance", "?")
        return f"Connected | Available balance: ₹{available}"
    else:
        raise Exception(f"API response: {resp}")

check("Dhan API connection + auth", test_dhan_connect)


# ─── CHECK 4: NIFTY spot price ────────────────────────────────────────────
def test_spot_price():
    import config
    from dhanhq import dhanhq
    from data_feed_dhan import DhanDataFeed

    dhan = dhanhq(config.DHAN["client_id"], config.DHAN["access_token"])
    feed = DhanDataFeed(dhan)
    spot = feed.get_spot_price()
    if spot and spot > 10000:
        return f"NIFTY spot = {spot:.2f}"
    raise Exception(f"Bad spot price: {spot}")

check("NIFTY 50 live spot price", test_spot_price)


# ─── CHECK 5: Historical candles ──────────────────────────────────────────
def test_candles():
    import config
    from dhanhq import dhanhq
    from data_feed_dhan import DhanDataFeed

    dhan = dhanhq(config.DHAN["client_id"], config.DHAN["access_token"])
    feed = DhanDataFeed(dhan)
    df   = feed.get_historical_candles(minutes=30)
    if df.empty:
        raise Exception("No candle data returned")
    last = df.iloc[-1]
    return (f"{len(df)} candles fetched | "
            f"Last: {last['date']} C={last['close']:.0f}")

check("Historical 5-min NIFTY candles", test_candles)


# ─── CHECK 6: Options chain ───────────────────────────────────────────────
def test_options():
    import config
    from dhanhq import dhanhq
    from data_feed_dhan import DhanDataFeed

    dhan = dhanhq(config.DHAN["client_id"], config.DHAN["access_token"])
    feed = DhanDataFeed(dhan)
    spot = feed.get_spot_price()
    snap = feed.get_atm_options_snapshot(spot)

    if not snap:
        raise Exception("Empty options snapshot")

    atm    = snap.get("atm", 0)
    ce_ltp = snap.get("ce", {}).get("ltp", 0)
    pe_ltp = snap.get("pe", {}).get("ltp", 0)
    ce_sid = snap.get("ce", {}).get("security_id", "")
    pe_sid = snap.get("pe", {}).get("security_id", "")

    if not ce_sid or not pe_sid:
        raise Exception(
            f"Missing security_id — CE:{ce_sid} PE:{pe_sid}. "
            "Check Dhan option chain API response format."
        )
    if ce_ltp == 0 and pe_ltp == 0:
        raise Exception("Both CE and PE LTP are 0 — market may be closed")

    return (f"ATM={atm} | CE={ce_ltp} (id={ce_sid}) | "
            f"PE={pe_ltp} (id={pe_sid})")

check("Options chain (CE + PE prices + security_id)", test_options)


# ─── CHECK 7: Telegram ────────────────────────────────────────────────────
def test_telegram():
    import config
    if "YOUR" in config.TELEGRAM.get("bot_token", "YOUR"):
        return "Telegram not configured (optional — skipping)"

    import requests
    token   = config.TELEGRAM["bot_token"]
    chat_id = config.TELEGRAM["chat_id"]
    url     = f"https://api.telegram.org/bot{token}/sendMessage"
    resp    = requests.post(url, json={
        "chat_id"   : chat_id,
        "text"      : (f"✅ PREMIA — Pre-flight test passed!\n"
                       f"🕐 {datetime.now().strftime('%d %b %Y %H:%M IST')}"),
        "parse_mode": "HTML",
    }, timeout=10)
    if resp.status_code == 200:
        return "Telegram message sent — check your phone!"
    raise Exception(f"Telegram error {resp.status_code}: {resp.text[:100]}")

check("Telegram bot alert", test_telegram)


# ─── SUMMARY ──────────────────────────────────────────────────────────────
print("\n" + "═"*55)
print(f"  RESULTS: {passed} passed, {failed} failed")
print("═"*55)

if failed == 0:
    print("""
  ✅ ALL CHECKS PASSED — You are ready for tomorrow!

  Run paper mode first:
    python main.py --paper

  When satisfied, go live:
    python main.py
""")
else:
    print(f"""
  ❌ {failed} CHECK(S) FAILED — Fix these before trading.

  Common fixes:
  • Dhan credentials → fill config.py DHAN section
  • dhanhq not installed → pip install dhanhq
  • Options security_id empty → market may be closed,
    try again tomorrow at 9:15 AM
  • Telegram → fill TELEGRAM section in config.py
    (optional but strongly recommended)
""")

sys.exit(0 if failed == 0 else 1)
