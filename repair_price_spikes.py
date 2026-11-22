#!/usr/bin/env python3
"""
repair_price_spikes.py — nightly sanity pass over the price folders.

Why (2026-11-22): daily_data_10y/SOXX.csv carried ~30 scattered bars at 3x the
series (unadjusted for its 3:1 split) and GLD.csv two bars at 10x. A bar on the
wrong SCALE is a vendor/adjustment fault, not a price move: no stock trades at
3x its neighbours for a day and comes straight back.

Rule: over the last LOOKBACK bars, a bar is "off-scale" when its Close is k times
the median Close of the WIN bars before it AND k times the median of the WIN bars
after it (so the series returns to scale — a real move does not), with k within
TOL of an integer factor 2..20 (or 1/k). Such a bar's Open/High/Low/Close are
divided (or multiplied) by that integer; Volume is scaled the other way. Anything
that is not close to an integer multiple is left alone and only reported.

  python3 repair_price_spikes.py            # repair in place, print what changed
  python3 repair_price_spikes.py --dry-run  # report only
Exit code is always 0; the nightly must not stop on this.
"""
import sys, glob, os
import numpy as np, pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
FOLDERS = ["daily_data_10y", "daily_data_v2"]
LOOKBACK, WIN, TOL = 400, 10, 0.12

def repair(path, dry):
    d = pd.read_csv(path)
    if "Close" not in d.columns or len(d) < 3 * WIN:
        return []
    c = pd.to_numeric(d["Close"], errors="coerce").values.astype(float)
    n = len(c); start = max(0, n - LOOKBACK); fixes = []
    for i in range(start, n):
        if not np.isfinite(c[i]) or c[i] <= 0:
            continue
        before = c[max(0, i - WIN):i]; after = c[i + 1:min(n, i + WIN + 1)]
        before = before[np.isfinite(before) & (before > 0)]; after = after[np.isfinite(after) & (after > 0)]
        if len(before) < 5:
            continue
        def factor(ref):
            r = c[i] / np.median(ref)
            for ratio, up in ((r, True), (1 / r, False)):
                k = round(ratio)
                if 2 <= k <= 20 and abs(ratio / k - 1) <= TOL:
                    return k if up else 1.0 / k
            return None
        fb = factor(before)
        if fb is None:
            continue
        if len(after) >= 3:
            # ISOLATION: the series must come back to the same scale afterwards. A real
            # move (MRNA Aug 2026 doubled and stayed; CAR Apr 2026 squeezed and fell)
            # does not, and is left alone.
            if factor(after) == fb:
                fixes.append((i, fb))
        elif fb >= 5 or fb <= 0.2:
            # newest bars have nothing after them yet: only fix the unmistakable (5x+);
            # a 2-4x bar waits a few nights until the series confirms it.
            fixes.append((i, fb))
    if fixes and not dry:
        for i, f in fixes:
            for col in ("Open", "High", "Low", "Close", "Adj Close"):
                if col in d.columns:
                    v = pd.to_numeric(d.at[i, col], errors="coerce")
                    if pd.notna(v): d.at[i, col] = v / f
            if "Volume" in d.columns:
                v = pd.to_numeric(d.at[i, "Volume"], errors="coerce")
                if pd.notna(v): d.at[i, "Volume"] = v * f
        d.to_csv(path, index=False)
    return [(str(d.iloc[i, 0])[:10], f) for i, f in fixes]

def main():
    dry = "--dry-run" in sys.argv; total = 0
    for folder in FOLDERS:
        for path in sorted(glob.glob(os.path.join(HERE, folder, "*.csv"))):
            try:
                fx = repair(path, dry)
                # a dense cluster pollutes its own medians; a second/third pass on the
                # cleaned series catches what the first could not see
                for _ in range(3):
                    if dry or not fx: break
                    more = repair(path, dry)
                    if not more: break
                    fx += more
            except Exception as e:
                print(f"  {os.path.basename(path)}: skipped ({e})"); continue
            if fx:
                total += len(fx)
                t = os.path.basename(path)[:-4]
                print(f"  {folder}/{t}: {len(fx)} off-scale bar(s) {'found' if dry else 'rescaled'}: "
                      + ", ".join(f"{dt} (x{f:g})" if f >= 1 else f"{dt} (x1/{round(1/f)})" for dt, f in fx[:8]) + (" …" if len(fx) > 8 else ""))
    print(f"repair_price_spikes: {total} off-scale bar(s) {'found' if dry else 'repaired'}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
