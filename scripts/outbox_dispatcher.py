import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.db import SessionLocal  # noqa: E402
from app.platform import dispatch_outbox_events  # noqa: E402


def process_once(batch_size: int) -> dict:
    with SessionLocal() as db:
        return dispatch_outbox_events(
            db=db, batch_size=max(1, min(int(batch_size), 500))
        )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Dispatch outbox events to Redis stream"
    )
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument("--poll-seconds", type=float, default=2.0)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()

    while True:
        result = process_once(args.batch_size)
        print(result)
        if args.once:
            return 0
        if int(result.get("processed", 0)) == 0:
            time.sleep(max(0.2, float(args.poll_seconds)))


if __name__ == "__main__":
    raise SystemExit(main())
