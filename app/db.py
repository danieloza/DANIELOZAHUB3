from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import settings

connect_args = {}
if settings.DATABASE_URL.startswith("sqlite"):
    connect_args = {"check_same_thread": False}

engine = create_engine(settings.DATABASE_URL, echo=False, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


def _sqlite_table_exists(conn, table_name: str) -> bool:
    row = conn.execute(
        text("SELECT name FROM sqlite_master WHERE type='table' AND name = :name"),
        {"name": table_name},
    ).first()
    return row is not None


def _sqlite_table_has_column(conn, table_name: str, column_name: str) -> bool:
    rows = conn.execute(text(f"PRAGMA table_info({table_name})")).fetchall()
    return any(r[1] == column_name for r in rows)


def _ensure_default_tenant(conn):
    conn.execute(
        text(
            """
            INSERT INTO tenants (slug, name)
            VALUES (:slug, :name)
            ON CONFLICT(slug) DO NOTHING
            """
        ),
        {"slug": settings.DEFAULT_TENANT_SLUG.strip().lower(), "name": settings.DEFAULT_TENANT_NAME.strip()},
    )


def _default_tenant_id(conn) -> int:
    row = conn.execute(
        text("SELECT id FROM tenants WHERE slug = :slug"),
        {"slug": settings.DEFAULT_TENANT_SLUG.strip().lower()},
    ).first()
    if not row:
        raise RuntimeError("Default tenant not found after migration")
    return int(row[0])


def _migrate_legacy_schema(conn):
    conn.execute(text("PRAGMA foreign_keys=OFF"))

    conn.execute(text("ALTER TABLE clients RENAME TO clients_legacy"))
    conn.execute(text("ALTER TABLE employees RENAME TO employees_legacy"))
    conn.execute(text("ALTER TABLE services RENAME TO services_legacy"))
    conn.execute(text("ALTER TABLE visits RENAME TO visits_legacy"))

    conn.execute(
        text(
            """
            CREATE TABLE clients (
                id INTEGER NOT NULL PRIMARY KEY,
                tenant_id INTEGER NOT NULL,
                name VARCHAR(120) NOT NULL,
                CONSTRAINT uq_clients_tenant_name UNIQUE (tenant_id, name),
                FOREIGN KEY(tenant_id) REFERENCES tenants (id)
            )
            """
        )
    )
    conn.execute(text("CREATE INDEX ix_clients_tenant_id ON clients (tenant_id)"))

    conn.execute(
        text(
            """
            CREATE TABLE employees (
                id INTEGER NOT NULL PRIMARY KEY,
                tenant_id INTEGER NOT NULL,
                name VARCHAR(120) NOT NULL,
                commission_pct NUMERIC(5,2) NOT NULL DEFAULT 0,
                CONSTRAINT uq_employees_tenant_name UNIQUE (tenant_id, name),
                FOREIGN KEY(tenant_id) REFERENCES tenants (id)
            )
            """
        )
    )
    conn.execute(text("CREATE INDEX ix_employees_tenant_id ON employees (tenant_id)"))

    conn.execute(
        text(
            """
            CREATE TABLE services (
                id INTEGER NOT NULL PRIMARY KEY,
                tenant_id INTEGER NOT NULL,
                name VARCHAR(120) NOT NULL,
                default_price NUMERIC(10,2) NOT NULL DEFAULT 0,
                CONSTRAINT uq_services_tenant_name UNIQUE (tenant_id, name),
                FOREIGN KEY(tenant_id) REFERENCES tenants (id)
            )
            """
        )
    )
    conn.execute(text("CREATE INDEX ix_services_tenant_id ON services (tenant_id)"))

    conn.execute(
        text(
            """
            CREATE TABLE visits (
                id INTEGER NOT NULL PRIMARY KEY,
                tenant_id INTEGER NOT NULL,
                dt DATETIME NOT NULL,
                client_id INTEGER NOT NULL,
                employee_id INTEGER NOT NULL,
                service_id INTEGER NOT NULL,
                price NUMERIC(10,2) NOT NULL DEFAULT 0,
                FOREIGN KEY(tenant_id) REFERENCES tenants (id),
                FOREIGN KEY(client_id) REFERENCES clients (id),
                FOREIGN KEY(employee_id) REFERENCES employees (id),
                FOREIGN KEY(service_id) REFERENCES services (id)
            )
            """
        )
    )
    conn.execute(text("CREATE INDEX ix_visits_tenant_id ON visits (tenant_id)"))

    tenant_id = _default_tenant_id(conn)
    conn.execute(
        text("INSERT INTO clients (tenant_id, name) SELECT :tenant_id, name FROM clients_legacy"),
        {"tenant_id": tenant_id},
    )
    conn.execute(
        text(
            "INSERT INTO employees (tenant_id, name, commission_pct) "
            "SELECT :tenant_id, name, commission_pct FROM employees_legacy"
        ),
        {"tenant_id": tenant_id},
    )
    conn.execute(
        text(
            "INSERT INTO services (tenant_id, name, default_price) "
            "SELECT :tenant_id, name, default_price FROM services_legacy"
        ),
        {"tenant_id": tenant_id},
    )

    conn.execute(
        text(
            """
            INSERT INTO visits (id, tenant_id, dt, client_id, employee_id, service_id, price)
            SELECT
                v.id,
                :tenant_id,
                v.dt,
                c.id,
                e.id,
                s.id,
                v.price
            FROM visits_legacy v
            JOIN clients_legacy lc ON lc.id = v.client_id
            JOIN employees_legacy le ON le.id = v.employee_id
            JOIN services_legacy ls ON ls.id = v.service_id
            JOIN clients c ON c.tenant_id = :tenant_id AND c.name = lc.name
            JOIN employees e ON e.tenant_id = :tenant_id AND e.name = le.name
            JOIN services s ON s.tenant_id = :tenant_id AND s.name = ls.name
            """
        ),
        {"tenant_id": tenant_id},
    )

    conn.execute(text("DROP TABLE visits_legacy"))
    conn.execute(text("DROP TABLE clients_legacy"))
    conn.execute(text("DROP TABLE employees_legacy"))
    conn.execute(text("DROP TABLE services_legacy"))

    conn.execute(text("PRAGMA foreign_keys=ON"))


def run_schema_migrations():
    if not settings.DATABASE_URL.startswith("sqlite"):
        return

    with engine.begin() as conn:
        conn.execute(text("PRAGMA foreign_keys=ON"))

        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS tenants (
                    id INTEGER NOT NULL PRIMARY KEY,
                    slug VARCHAR(80) NOT NULL UNIQUE,
                    name VARCHAR(120) NOT NULL UNIQUE
                )
                """
            )
        )
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_tenants_slug ON tenants (slug)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_tenants_name ON tenants (name)"))

        _ensure_default_tenant(conn)

        if _sqlite_table_exists(conn, "visits") and not _sqlite_table_has_column(conn, "visits", "tenant_id"):
            _migrate_legacy_schema(conn)

        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS reservation_requests (
                    id INTEGER NOT NULL PRIMARY KEY,
                    tenant_id INTEGER NOT NULL,
                    created_at DATETIME NOT NULL,
                    requested_dt DATETIME NOT NULL,
                    client_name VARCHAR(120) NOT NULL,
                    phone VARCHAR(40),
                    service_name VARCHAR(120) NOT NULL,
                    note VARCHAR(500),
                    status VARCHAR(32) NOT NULL DEFAULT 'new',
                    converted_visit_id INTEGER,
                    converted_at DATETIME,
                    idempotency_key VARCHAR(120),
                    FOREIGN KEY(tenant_id) REFERENCES tenants (id)
                )
                """
            )
        )

        if not _sqlite_table_has_column(conn, "reservation_requests", "converted_visit_id"):
            conn.execute(text("ALTER TABLE reservation_requests ADD COLUMN converted_visit_id INTEGER"))
        if not _sqlite_table_has_column(conn, "reservation_requests", "converted_at"):
            conn.execute(text("ALTER TABLE reservation_requests ADD COLUMN converted_at DATETIME"))
        if not _sqlite_table_has_column(conn, "reservation_requests", "idempotency_key"):
            conn.execute(text("ALTER TABLE reservation_requests ADD COLUMN idempotency_key VARCHAR(120)"))

        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_reservation_requests_tenant_id ON reservation_requests (tenant_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_reservation_requests_created_at ON reservation_requests (created_at)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_reservation_requests_requested_dt ON reservation_requests (requested_dt)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_reservation_requests_status ON reservation_requests (status)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_reservation_requests_converted_visit_id ON reservation_requests (converted_visit_id)"))
        conn.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_reservation_tenant_idempotency "
                "ON reservation_requests (tenant_id, idempotency_key)"
            )
        )

        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS reservation_status_events (
                    id INTEGER NOT NULL PRIMARY KEY,
                    tenant_id INTEGER NOT NULL,
                    reservation_id INTEGER NOT NULL,
                    created_at DATETIME NOT NULL,
                    from_status VARCHAR(32),
                    to_status VARCHAR(32) NOT NULL,
                    action VARCHAR(40) NOT NULL DEFAULT 'status_update',
                    actor VARCHAR(120),
                    note VARCHAR(300),
                    FOREIGN KEY(tenant_id) REFERENCES tenants (id),
                    FOREIGN KEY(reservation_id) REFERENCES reservation_requests (id)
                )
                """
            )
        )
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_reservation_status_events_tenant_id ON reservation_status_events (tenant_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_reservation_status_events_reservation_id ON reservation_status_events (reservation_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_reservation_status_events_created_at ON reservation_status_events (created_at)"))


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
