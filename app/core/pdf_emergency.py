from datetime import date
from io import BytesIO
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet

def generate_day_plan_pdf(day: date, visits: list[dict]) -> bytes:
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4)
    elements = []
    styles = getSampleStyleSheet()

    # Title
    elements.append(Paragraph(f"Plan Dnia: {day.isoformat()}", styles['Title']))
    elements.append(Spacer(1, 12))

    if not visits:
        elements.append(Paragraph("Brak wizyt na ten dzień.", styles['Normal']))
    else:
        # Table Data
        data = [["Godzina", "Klient", "Usługa", "Pracownik", "Notatka"]]
        for v in visits:
            data.append([
                v.get('time', '00:00'),
                v.get('client', '-'),
                v.get('service', '-'),
                v.get('employee', '-'),
                v.get('note', '')[:30]  # Truncate note
            ])

        # Table Style
        table = Table(data, colWidths=[60, 120, 120, 80, 150])
        style = TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
            ('GRID', (0, 0), (-1, -1), 1, colors.black),
        ])
        table.setStyle(style)
        elements.append(table)

    elements.append(Spacer(1, 24))
    elements.append(Paragraph("Wygenerowano automatycznie przez SalonOS Emergency System.", styles['Italic']))

    doc.build(elements)
    buffer.seek(0)
    return buffer.read()
