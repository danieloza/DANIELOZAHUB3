import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bot.keyboards import main_menu  # noqa: E402


def _menu_callbacks() -> list[str]:
    kb = main_menu()
    callbacks: list[str] = []
    for row in kb.inline_keyboard:
        for button in row:
            callbacks.append(str(button.callback_data or ""))
    return callbacks


def _router_has_wow_aliases() -> bool:
    src = (ROOT / "bot" / "router_bot.py").read_text(encoding="utf-8")
    return bool(
        re.search(r'data\s*==\s*"WOW:START"', src)
        and re.search(r'data\s*=\s*"TODAY"', src)
        and re.search(r'data\s*==\s*"WOW:ADD"', src)
        and re.search(r'data\s*=\s*"ADD_VISIT"', src)
    )


def main() -> int:
    callbacks = _menu_callbacks()
    required = {
        "WOW:START",
        "WOW:ADD",
        "SL:MENU",
        "CRM:MENU",
        "ST:MENU",
        "AV:MENU",
        "BF:MENU",
        "CRM:ASSIST",
        "MONTH",
        "CSV_MONTH",
        "PDF_MONTH",
    }
    missing = sorted(required.difference(callbacks))
    has_aliases = _router_has_wow_aliases()
    output = {
        "ok": not missing and has_aliases,
        "callbacks_count": len(callbacks),
        "callbacks": callbacks,
        "missing_required_callbacks": missing,
        "router_has_wow_aliases": has_aliases,
    }
    print(json.dumps(output, ensure_ascii=True))
    return 0 if output["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
