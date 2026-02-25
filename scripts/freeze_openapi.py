import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.main import app  # noqa: E402


def main() -> int:
    out_path = ROOT / "openapi_contract.json"
    schema = app.openapi()
    out_path.write_text(
        json.dumps(schema, ensure_ascii=True, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    print(f"Wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
