import json
import os
import uuid
from pathlib import Path

import psycopg


def main():
    prefix = "demo-" + uuid.uuid4().hex[:8]
    with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as conn:
        conn.execute(Path("sql/source.sql").read_text())
        with conn.transaction():
            for index in range(20):
                conn.execute(
                    "INSERT INTO transactions(id,amount_minor,currency,status,attributes) VALUES (%s,%s,%s,%s,%s)",
                    (
                        f"{prefix}-{index}",
                        10000 + 125 * index,
                        "USD" if index % 2 else "INR",
                        "settled",
                        json.dumps({"region": "APAC", "channel": "api", "synthetic": True}),
                    ),
                )
            conn.execute("UPDATE transactions SET amount_minor=25000 WHERE id=%s", (f"{prefix}-0",))
            conn.execute("DELETE FROM transactions WHERE id=%s", (f"{prefix}-1",))
    print(f"Committed 20 inserts, one update and one delete. Prefix: {prefix}")


if __name__ == "__main__":
    main()
