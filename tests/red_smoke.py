"""Initial dependency-free red test: first insert must become queryable."""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
from fluxlake.lake import Lake

with tempfile.TemporaryDirectory() as directory:
    lake = Lake(Path(directory))
    result = lake.apply(
        [
            {
                "event_id": "e1",
                "key": "tx1",
                "version": 1,
                "op": "insert",
                "occurred_at": "2026-10-30T10:00:00+00:00",
                "data": {"amount_minor": 12500, "currency": "USD", "status": "settled"},
            }
        ]
    )
    assert result["applied"] == 1
    assert lake.current()[0]["amount_minor"] == 12500
