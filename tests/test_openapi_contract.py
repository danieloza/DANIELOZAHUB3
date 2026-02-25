import json
from pathlib import Path

from app.main import app


def _normalized(value: dict) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def test_openapi_contract_is_frozen():
    contract_path = Path(__file__).resolve().parents[1] / "openapi_contract.json"
    assert contract_path.exists(), (
        "openapi_contract.json is missing; run: python scripts/freeze_openapi.py"
    )

    expected = json.loads(contract_path.read_text(encoding="utf-8"))
    current = app.openapi()

    assert _normalized(current) == _normalized(expected), (
        "OpenAPI contract changed; run: python scripts/freeze_openapi.py"
    )
