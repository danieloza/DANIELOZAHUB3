from io import BytesIO
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas


def build_month_report_pdf(
    month_label: str,
    total: float,
    count: int,
    by_emp: list[tuple[str, float, float, float]],
) -> bytes:
    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)

    width, height = A4
    y = height - 50

    c.setFont("Helvetica-Bold", 16)
    c.drawString(40, y, f"Danex — Raport miesiąca: {month_label}")
    y -= 30

    c.setFont("Helvetica", 12)
    c.drawString(40, y, f"Liczba wizyt: {count}")
    y -= 18
    c.drawString(40, y, f"Utarg miesiąca: {total:.2f} PLN")
    y -= 30

    c.setFont("Helvetica-Bold", 12)
    c.drawString(40, y, "Prowizje pracowników:")
    y -= 20

    c.setFont("Helvetica", 11)
    for name, pct, revenue, comm in by_emp:
        line = (
            f"- {name}: przychód {revenue:.2f} PLN | "
            f"prowizja {pct:.2f}% = {comm:.2f} PLN"
        )
        c.drawString(50, y, line[:110])
        y -= 16

        if y < 60:
            c.showPage()
            y = height - 50
            c.setFont("Helvetica", 11)

    c.showPage()
    c.save()
    return buf.getvalue()
