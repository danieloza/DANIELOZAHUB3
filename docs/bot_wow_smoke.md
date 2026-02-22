# Bot WOW Menu Smoke

Quick manual smoke for new WOW menu actions.

## Preconditions
- API and bot are running.
- Telegram bot token is configured in `.env`.
- Test tenant has at least one employee and one service.

## Steps
1. Open Telegram chat with bot and run `/start`.
2. Verify top row shows `Start dnia` and `Dodaj wizyte`.
3. Click `Start dnia`.
4. Verify bot shows employee selector for current day.
5. Click `Dodaj wizyte`.
6. Verify bot starts add-visit flow and asks for employee.
7. Return to `/menu`.
8. Click `Slot Engine`, `CRM 360`, `Status Flow`, `Dostepnosc Live`, `Bufory Pro`, `Pulse Assistant`.
9. Verify each action opens expected module menu or flow (no `Nieznana akcja` message).
10. Click `Raport miesiaca`, `CSV`, `PDF` and confirm month prompt appears (`YYYY-MM`).

## Fast automation
Run:

```powershell
.\.venv\Scripts\python.exe scripts\bot_wow_smoke.py
```

Expected result:
- JSON with `"ok": true`
