#!/usr/bin/env python3
"""One-time migration: convert anchor_x / anchor_y from PDF points to image pixels."""
import sqlite3, sys, os

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "dev.db")
SCALE = 300 / 72.0  # PDF points → image pixels at 300 DPI

conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()

cur.execute("SELECT MAX(anchor_x) FROM dimensions")
max_x = cur.fetchone()[0] or 0
if max_x > 3000:
    print(f"anchor_x max={max_x:.0f} — looks like pixels already, skipping.")
    conn.close()
    sys.exit(0)

cur.execute("""
    UPDATE dimensions
    SET anchor_x = anchor_x * ?,
        anchor_y = anchor_y * ?
    WHERE anchor_x IS NOT NULL
""", (SCALE, SCALE))
print(f"Updated {cur.rowcount} rows (scale={SCALE:.4f})")
conn.commit()
conn.close()
print("Done.")
