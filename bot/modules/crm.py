from datetime import date

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from bot.api import (
    create_client_note,
    fetch_assistant_actions,
    fetch_client_detail,
    fetch_client_search,
    fetch_day_pulse,
)
from bot.keyboards import main_menu


def _crm_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🔎 Szukaj klienta", callback_data="CRM:SEARCH")],
            [InlineKeyboardButton("⚡ Pulse + Assistant", callback_data="CRM:ASSIST")],
            [InlineKeyboardButton("⬅️ Menu", callback_data="CRM:BACK")],
        ]
    )


def _format_client_detail(detail: dict) -> str:
    lines = [
        f"👤 {detail.get('name')} (ID: {detail.get('id')})",
        f"📞 {detail.get('phone') or '-'}",
        f"🧾 Wizyty: {detail.get('visits_count', 0)}",
    ]
    if detail.get("last_visit_dt"):
        lines.append(f"🕒 Ostatnia: {detail.get('last_visit_dt')}")
    lines.append("")
    visits = detail.get("visits") or []
    if visits:
        lines.append("Ostatnie wizyty:")
        for v in visits[:5]:
            lines.append(
                f"- {v.get('dt')} | {v.get('service_name')} | {v.get('employee_name')} | {v.get('price')} zł | {v.get('status')}"
            )
    notes = detail.get("notes") or []
    if notes:
        lines.append("")
        lines.append("Notatki:")
        for n in notes[:3]:
            lines.append(f"- {n.get('created_at')}: {n.get('note')}")
    return "\n".join(lines)


def _client_kb(client_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "📝 Dodaj notatkę", callback_data=f"CRM:NOTE:{client_id}"
                )
            ],
            [InlineKeyboardButton("⬅️ CRM", callback_data="CRM:MENU")],
        ]
    )


async def on_callback(update, context, data: str) -> bool:
    if not data.startswith("CRM:"):
        return False
    q = update.callback_query

    if data in ("CRM:MENU",):
        context.user_data["crm_awaiting_search"] = False
        context.user_data["crm_note_client_id"] = None
        await q.message.reply_text("CRM:", reply_markup=_crm_menu())
        return True

    if data in ("CRM:BACK",):
        await q.message.reply_text("Menu:", reply_markup=main_menu())
        return True

    if data == "CRM:SEARCH":
        context.user_data["crm_awaiting_search"] = True
        await q.message.reply_text("Wpisz min. 2 znaki (imię lub telefon).")
        return True

    if data == "CRM:ASSIST":
        today_iso = date.today().isoformat()
        pulse = fetch_day_pulse(today_iso) or {}
        actions = fetch_assistant_actions(limit=6)
        lines = [
            f"⚡ Pulse {today_iso}",
            f"- revenue: {pulse.get('total_revenue', 0)} zł",
            f"- wizyty: {pulse.get('visits_count', 0)}",
            f"- konwersja: {pulse.get('conversion_rate', 0)}",
            f"- rezerwacje new/contacted: {pulse.get('reservations_new', 0)}/{pulse.get('reservations_contacted', 0)}",
            "",
            "Assistant:",
        ]
        if actions:
            for a in actions[:6]:
                lines.append(
                    f"- #{a.get('reservation_id')} {a.get('client_name')} [{a.get('status')}] -> {a.get('suggested_action')}"
                )
        else:
            lines.append("- brak otwartych zadań")
        await q.message.reply_text("\n".join(lines), reply_markup=_crm_menu())
        return True

    if data.startswith("CRM:OPEN:"):
        client_id = int(data.split("CRM:OPEN:")[1])
        detail = fetch_client_detail(client_id)
        if not detail:
            await q.message.reply_text(
                "Nie znaleziono klienta.", reply_markup=_crm_menu()
            )
            return True
        await q.message.reply_text(
            _format_client_detail(detail), reply_markup=_client_kb(client_id)
        )
        return True

    if data.startswith("CRM:NOTE:"):
        client_id = int(data.split("CRM:NOTE:")[1])
        context.user_data["crm_note_client_id"] = client_id
        await q.message.reply_text("Wpisz treść notatki klienta:")
        return True

    await q.message.reply_text("Nieznana akcja CRM.", reply_markup=_crm_menu())
    return True


async def on_text(update, context) -> bool:
    if context.user_data.get("crm_awaiting_search"):
        query = (update.message.text or "").strip()
        if len(query) < 2:
            await update.message.reply_text("Podaj min. 2 znaki.")
            return True
        rows = fetch_client_search(query, limit=8)
        context.user_data["crm_awaiting_search"] = False
        if not rows:
            await update.message.reply_text("Brak wyników.", reply_markup=_crm_menu())
            return True
        kb = [
            [
                InlineKeyboardButton(
                    f"{r.get('name')} ({r.get('phone') or '-'})",
                    callback_data=f"CRM:OPEN:{r.get('id')}",
                )
            ]
            for r in rows
        ]
        kb.append([InlineKeyboardButton("⬅️ CRM", callback_data="CRM:MENU")])
        await update.message.reply_text(
            "Wyniki:", reply_markup=InlineKeyboardMarkup(kb)
        )
        return True

    client_id = context.user_data.get("crm_note_client_id")
    if client_id:
        txt = (update.message.text or "").strip()
        if len(txt) < 2:
            await update.message.reply_text("Notatka za krótka.")
            return True
        created = create_client_note(int(client_id), txt)
        context.user_data["crm_note_client_id"] = None
        if not created:
            await update.message.reply_text(
                "Nie udało się zapisać notatki.", reply_markup=_crm_menu()
            )
            return True
        detail = fetch_client_detail(int(client_id))
        if detail:
            await update.message.reply_text(
                "✅ Zapisano notatkę.\n\n" + _format_client_detail(detail),
                reply_markup=_client_kb(int(client_id)),
            )
        else:
            await update.message.reply_text(
                "✅ Zapisano notatkę.", reply_markup=_crm_menu()
            )
        return True

    return False
