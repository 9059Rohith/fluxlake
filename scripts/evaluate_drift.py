"""Run deterministic bounded synthetic DriftLab experiments; never accesses a database."""

import argparse
import json
from pathlib import Path

from fluxlake.drift_scenarios import evaluate


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=20261030)
    parser.add_argument("--trials", type=int, default=60)
    parser.add_argument("--samples", type=int, default=400)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        result = evaluate(args.seed, args.trials, args.samples)
    except ValueError as error:
        parser.error(str(error))
    body = json.dumps(result, indent=2, allow_nan=False) + "\n"
    if args.output:
        args.output.write_text(body, encoding="utf-8")
    print(
        json.dumps(
            {
                name: {key: value for key, value in outcome.items() if key != "trials"}
                for name, outcome in result["scenarios"].items()
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
