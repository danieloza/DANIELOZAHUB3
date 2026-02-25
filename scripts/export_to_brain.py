import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from sqlalchemy import func, select, text

# Add parent dir to path to import app modules
sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.db import SessionLocal
from app.models import Employee, Visit, Service

RAG_KNOWLEDGE_PATH = Path(__file__).resolve().parents[2] / "python-rag-langchain" / "knowledge.txt"

def generate_financial_narrative():
    db = SessionLocal()
    try:
        # 1. Okres analizy (ostatnie 30 dni)
        end_date = datetime.now()
        start_date = end_date - timedelta(days=30)
        
        # 2. Pobieranie danych
        visits = db.execute(
            select(Visit).where(Visit.dt >= start_date, Visit.status == "completed")
        ).scalars().all()
        
        employees = db.execute(select(Employee)).scalars().all()
        
        # 3. Agregacja
        total_revenue = sum(float(v.price) for v in visits)
        visit_count = len(visits)
        avg_ticket = total_revenue / visit_count if visit_count > 0 else 0
        
        emp_stats = {}
        for v in visits:
            emp_name = v.employee.name if v.employee else "Nieznany"
            if emp_name not in emp_stats:
                emp_stats[emp_name] = {"count": 0, "revenue": 0.0}
            emp_stats[emp_name]["count"] += 1
            emp_stats[emp_name]["revenue"] += float(v.price)

        # 4. Generowanie tekstu dla AI (Narrative Generation)
        lines = [
            f"RAPORT BIZNESOWY FRESH.COM (Generowany: {datetime.now().strftime('%Y-%m-%d %H:%M')})",
            "---",
            "### Ogólna Kondycja Biznesu (Ostatnie 30 dni)",
            f"Łączny przychód wyniósł {total_revenue:.2f} PLN przy {visit_count} wizytach.",
            f"Średnia wartość paragonu (Average Ticket) to {avg_ticket:.2f} PLN.",
            "Wnioski ogólne: ",
            "Firma jest w fazie stabilnej." if total_revenue > 10000 else "Firma wymaga intensyfikacji marketingu.",
            "",
            "### Wyniki Zespołu (Ranking)",
        ]

        sorted_emps = sorted(emp_stats.items(), key=lambda x: x[1]['revenue'], reverse=True)
        
        for name, stats in sorted_emps:
            lines.append(f"- {name}: Utarg {stats['revenue']:.2f} PLN ({stats['count']} wizyt). Średnia: {stats['revenue']/stats['count']:.2f} PLN.")
            
        # Dodanie "osobowości" pracowników na bazie bazy danych
        lines.append("\n### Profile Pracowników (Kontekst HR)")
        for e in employees:
            status = "Aktywny" if e.is_active else "Nieaktywny"
            lines.append(f"- {e.name}: {status}. Specjalizacja: {e.specialties or 'Ogólna'}. Rating: {e.rating}/5.0.")

        # Zapis do RAG
        content = "\n".join(lines)
        
        # Zachowaj statyczny kontekst (jeśli istnieje) i dodaj dynamiczny
        static_context = "Fresh.com to luksusowy salon beauty. Właścicielem jest Daniel. Systemem zarządza BeautyOS."
        
        full_knowledge = f"{static_context}\n\n{content}"
        
        with open(RAG_KNOWLEDGE_PATH, "w", encoding="utf-8") as f:
            f.write(full_knowledge)
            
        print(f"✅ AI Brain zaktualizowany! Dane zapisano w: {RAG_KNOWLEDGE_PATH}")
        print("Przykładowe dane:")
        print(content[:200] + "...")

    except Exception as e:
        print(f"❌ Błąd generowania wiedzy: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    generate_financial_narrative()
