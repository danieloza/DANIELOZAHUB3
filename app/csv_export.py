import csv
from io import StringIO

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Visit


def export_visits_csv(db: Session, tenant_id: int, start_dt, end_dt) -> str:
    out = StringIO()
    w = csv.writer(out)
    w.writerow(
        ["id", "dt", "client", "employee", "service", "price", "duration_min", "status"]
    )

    visits = (
        db.execute(
            select(Visit)
            .where(
                Visit.tenant_id == tenant_id,
                Visit.dt >= start_dt,
                Visit.dt < end_dt,
            )
            .order_by(Visit.dt.asc())
        )
        .scalars()
        .all()
    )

    for v in visits:
        w.writerow(
            [
                v.id,
                v.dt.isoformat(),
                v.client.name,
                v.employee.name,
                v.service.name,
                float(v.price),
                int(v.duration_min or 30),
                v.status or "planned",
            ]
        )

    return out.getvalue()
