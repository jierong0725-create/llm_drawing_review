import sqlite3, sys

for db in ("dev.db", "review.db"):
    try:
        con = sqlite3.connect(db)
        cols = [r[1] for r in con.execute("PRAGMA table_info(dimensions)").fetchall()]
        if "rotation_deg" not in cols:
            con.execute("ALTER TABLE dimensions ADD COLUMN rotation_deg REAL NOT NULL DEFAULT 0.0")
            con.commit()
            print(f"{db}: added rotation_deg")
        else:
            print(f"{db}: already has rotation_deg")
        con.close()
    except sqlite3.OperationalError as e:
        print(f"{db}: skipped ({e})", file=sys.stderr)
