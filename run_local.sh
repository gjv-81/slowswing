#!/bin/bash
# ============================================================================
# run_local.sh — STS local beta server (no host, no domain, no cost).
#
# Rebuilds board.json from your latest STS_holy_grail.xlsx, then serves the
# site on your laptop. Open the printed URL in any browser.
#
#   bash run_local.sh              # rebuild + serve
#
# Uses the workbook's own prices (PC_SOURCE=workbook): fully offline, always
# builds, never blocked by the freshness guard — ideal for laptop beta. The
# live vendor pull (Marketstack/Polygon via .env) is for the production nightly
# job; to test it locally instead, run:  python3 build_board.py
#
# Stop the server with Ctrl+C.
# ============================================================================
cd "$(dirname "$0")" || exit 1

PORT="${PORT:-8000}"
# Prefer python3.12 (where the pipeline's yfinance lives); fall back to python3.
PY="python3"; command -v python3.12 >/dev/null 2>&1 && PY="python3.12"

echo "① Updating market regime (SPY/QQQ) ..."
$PY build_regime.py || echo "   (regime not refreshed — keeping last regime.json)"

echo "② Rebuilding board.json from STS_holy_grail.xlsx (workbook prices) ..."
if PC_SOURCE=workbook $PY build_board.py; then
  echo "   board.json refreshed."
else
  echo "   (build_board did not refresh — serving the existing board.json / inlined snapshot.)"
fi

echo
echo "③ Serving on your laptop. Open this in your browser:"
echo "      http://localhost:${PORT}/sts_site_live.html"
echo "   (only this computer can see it — Ctrl+C to stop)"
echo
$PY -m http.server "${PORT}"
