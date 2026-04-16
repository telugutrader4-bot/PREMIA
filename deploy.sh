#!/bin/bash
# ═══════════════════════════════════════════════════════════════════
# deploy.sh — PREMIA Auto-Setup Script for Oracle Cloud Ubuntu VM
# Run this once on a fresh Ubuntu 22.04 VM:
#   chmod +x deploy.sh && ./deploy.sh
# ═══════════════════════════════════════════════════════════════════

set -e
echo ""
echo "=============================================="
echo "  PREMIA — Oracle Cloud Deployment Setup"
echo "=============================================="
echo ""

# ── 1. System update ──────────────────────────────────────────────
echo "[1/7] Updating system packages..."
sudo apt-get update -qq
sudo apt-get install -y python3 python3-pip python3-venv git unzip curl screen -qq

# ── 2. Create PREMIA directory ────────────────────────────────────
echo "[2/7] Setting up PREMIA directory..."
mkdir -p /home/ubuntu/PREMIA/logs
mkdir -p /home/ubuntu/PREMIA/trades

# ── 3. Python virtual environment ────────────────────────────────
echo "[3/7] Creating Python virtual environment..."
cd /home/ubuntu/PREMIA
python3 -m venv venv
source venv/bin/activate

# ── 4. Install dependencies ───────────────────────────────────────
echo "[4/7] Installing Python packages..."
pip install --quiet --upgrade pip
pip install --quiet dhanhq requests pandas numpy

# ── 5. Copy systemd service ───────────────────────────────────────
echo "[5/7] Installing PREMIA as system service..."
sudo cp /home/ubuntu/PREMIA/premia.service /etc/systemd/system/premia.service
sudo systemctl daemon-reload
sudo systemctl enable premia.service

# ── 6. Open firewall for Telegram (outbound only — no inbound needed)
echo "[6/7] Firewall: outbound HTTPS already allowed by default"

# ── 7. Done ───────────────────────────────────────────────────────
echo ""
echo "[7/7] Setup complete!"
echo ""
echo "=============================================="
echo "  NEXT STEPS:"
echo "  1. Upload your PREMIA Python files to /home/ubuntu/PREMIA/"
echo "  2. sudo systemctl start premia"
echo "  3. sudo systemctl status premia"
echo "  4. Check logs: tail -f /home/ubuntu/PREMIA/logs/premia.log"
echo "=============================================="
echo ""
