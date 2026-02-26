from sqlalchemy import create_engine, text, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import settings

connect_args = {}
if settings.DATABASE_URL.startswith("sqlite"):
    connect_args = {"check_same_thread": False}

engine = create_engine(settings.DATABASE_URL, echo=False, connect_args=connect_args)

# Senior IT: Enable Write-Ahead Logging (WAL) for SQLite concurrency
if settings.DATABASE_URL.startswith("sqlite"):
    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.close()

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
        {
            "slug": settings.DEFAULT_TENANT_SLUG.strip().lower(),
            "name": settings.DEFAULT_TENANT_NAME.strip(),
        },
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
                phone VARCHAR(40),
                CONSTRAINT uq_clients_tenant_name UNIQUE (tenant_id, name),
                FOREIGN KEY(tenant_id) REFERENCES tenants (id)
            )
            """
        )
    )
    conn.execute(text("CREATE INDEX ix_clients_tenant_id ON clients (tenant_id)"))
    conn.execute(text("CREATE INDEX ix_clients_phone ON clients (phone)"))

    conn.execute(
        text(
            """
            CREATE TABLE employees (
                id INTEGER NOT NULL PRIMARY KEY,
                tenant_id INTEGER NOT NULL,
                name VARCHAR(120) NOT NULL,
                commission_pct NUMERIC(5,2) NOT NULL DEFAULT 0,
                is_active BOOLEAN NOT NULL DEFAULT 1,
                CONSTRAINT uq_employees_tenant_name UNIQUE (tenant_id, name),
                FOREIGN KEY(tenant_id) REFERENCES tenants (id)
            )
            """
        )
    )
    conn.execute(text("CREATE INDEX ix_employees_tenant_id ON employees (tenant_id)"))
    conn.execute(text("CREATE INDEX ix_employees_is_active ON employees (is_active)"))

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
                source_reservation_id INTEGER,
                price NUMERIC(10,2) NOT NULL DEFAULT 0,
                duration_min INTEGER NOT NULL DEFAULT 30,
                status VARCHAR(32) NOT NULL DEFAULT 'planned',
                FOREIGN KEY(tenant_id) REFERENCES tenants (id),
                FOREIGN KEY(client_id) REFERENCES clients (id),
                FOREIGN KEY(employee_id) REFERENCES employees (id),
                FOREIGN KEY(service_id) REFERENCES services (id)
            )
            """
        )
    )
    conn.execute(text("CREATE INDEX ix_visits_tenant_id ON visits (tenant_id)"))
    conn.execute(text("CREATE INDEX ix_visits_dt ON visits (dt)"))
    conn.execute(text("CREATE INDEX ix_visits_status ON visits (status)"))
    conn.execute(
        text(
            "CREATE INDEX ix_visits_source_reservation_id ON visits (source_reservation_id)"
        )
    )
    conn.execute(
        text(
            "CREATE UNIQUE INDEX uq_visits_tenant_source_reservation ON visits (tenant_id, source_reservation_id)"
        )
    )

    tenant_id = _default_tenant_id(conn)
    conn.execute(
        text(
            "INSERT INTO clients (tenant_id, name) SELECT :tenant_id, name FROM clients_legacy"
        ),
        {"tenant_id": tenant_id},
    )
    conn.execute(
        text(
            "INSERT INTO employees (tenant_id, name, commission_pct, is_active) "
            "SELECT :tenant_id, name, commission_pct, 1 FROM employees_legacy"
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
            INSERT INTO visits (id, tenant_id, dt, client_id, employee_id, service_id, source_reservation_id, price, duration_min, status)
            SELECT
                v.id,
                :tenant_id,
                v.dt,
                c.id,
                e.id,
                s.id,
                NULL,
                v.price,
                30,
                'planned'
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
        conn.execute(
            text("CREATE INDEX IF NOT EXISTS ix_tenants_slug ON tenants (slug)")
        )
        conn.execute(
            text("CREATE INDEX IF NOT EXISTS ix_tenants_name ON tenants (name)")
        )

        if _sqlite_table_exists(conn, "tenants"):
            if not _sqlite_table_has_column(conn, "tenants", "logo_url"):
                conn.execute(text("ALTER TABLE tenants ADD COLUMN logo_url VARCHAR(500)"))
            if not _sqlite_table_has_column(conn, "tenants", "headline"):
                conn.execute(text("ALTER TABLE tenants ADD COLUMN headline VARCHAR(200)"))
            if not _sqlite_table_has_column(conn, "tenants", "about_us"):
                conn.execute(text("ALTER TABLE tenants ADD COLUMN about_us TEXT"))
            if not _sqlite_table_has_column(conn, "tenants", "address"):
                conn.execute(text("ALTER TABLE tenants ADD COLUMN address VARCHAR(255)"))
            if not _sqlite_table_has_column(conn, "tenants", "city"):
                conn.execute(text("ALTER TABLE tenants ADD COLUMN city VARCHAR(100)"))
            if not _sqlite_table_has_column(conn, "tenants", "google_maps_url"):
                conn.execute(
                    text("ALTER TABLE tenants ADD COLUMN google_maps_url VARCHAR(500)")
                )
            if not _sqlite_table_has_column(conn, "tenants", "instagram_url"):
                conn.execute(
                    text("ALTER TABLE tenants ADD COLUMN instagram_url VARCHAR(255)")
                )
            if not _sqlite_table_has_column(conn, "tenants", "facebook_url"):
                conn.execute(
                    text("ALTER TABLE tenants ADD COLUMN facebook_url VARCHAR(255)")
                )
            if not _sqlite_table_has_column(conn, "tenants", "website_url"):
                conn.execute(text("ALTER TABLE tenants ADD COLUMN website_url VARCHAR(255)"))
            if not _sqlite_table_has_column(conn, "tenants", "contact_email"):
                conn.execute(
                    text("ALTER TABLE tenants ADD COLUMN contact_email VARCHAR(160)")
                )
            if not _sqlite_table_has_column(conn, "tenants", "contact_phone"):
                conn.execute(
                    text("ALTER TABLE tenants ADD COLUMN contact_phone VARCHAR(40)")
                )
            if not _sqlite_table_has_column(conn, "tenants", "industry_type"):
                conn.execute(
                    text(
                        "ALTER TABLE tenants ADD COLUMN industry_type VARCHAR(50) NOT NULL DEFAULT 'general_beauty'"
                    )
                )
            if not _sqlite_table_has_column(conn, "tenants", "rating_avg"):
                conn.execute(
                    text(
                        "ALTER TABLE tenants ADD COLUMN rating_avg NUMERIC(3,2) NOT NULL DEFAULT 5.0"
                    )
                )
            if not _sqlite_table_has_column(conn, "tenants", "created_at"):
                conn.execute(text("ALTER TABLE tenants ADD COLUMN created_at DATETIME"))
                conn.execute(
                    text(
                        "UPDATE tenants SET created_at = CURRENT_TIMESTAMP WHERE created_at IS NULL"
                    )
                )

        _ensure_default_tenant(conn)

        if _sqlite_table_exists(conn, "visits") and not _sqlite_table_has_column(
            conn, "visits", "tenant_id"
        ):
            _migrate_legacy_schema(conn)

        if _sqlite_table_exists(conn, "clients"):
            if not _sqlite_table_has_column(conn, "clients", "phone"):
                conn.execute(text("ALTER TABLE clients ADD COLUMN phone VARCHAR(40)"))
            conn.execute(
                text("CREATE INDEX IF NOT EXISTS ix_clients_phone ON clients (phone)")
            )

        if _sqlite_table_exists(conn, "employees"):
            if not _sqlite_table_has_column(conn, "employees", "is_active"):
                conn.execute(
                    text(
                        "ALTER TABLE employees ADD COLUMN is_active BOOLEAN NOT NULL DEFAULT 1"
                    )
                )
            conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_employees_is_active ON employees (is_active)"
                )
            )

        if _sqlite_table_exists(conn, "visits"):
            if not _sqlite_table_has_column(conn, "visits", "duration_min"):
                conn.execute(
                    text(
                        "ALTER TABLE visits ADD COLUMN duration_min INTEGER NOT NULL DEFAULT 30"
                    )
                )
            if not _sqlite_table_has_column(conn, "visits", "status"):
                conn.execute(
                    text(
                        "ALTER TABLE visits ADD COLUMN status VARCHAR(32) NOT NULL DEFAULT 'planned'"
                    )
                )
            if not _sqlite_table_has_column(conn, "visits", "source_reservation_id"):
                conn.execute(
                    text("ALTER TABLE visits ADD COLUMN source_reservation_id INTEGER")
                )
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_visits_dt ON visits (dt)"))
            conn.execute(
                text("CREATE INDEX IF NOT EXISTS ix_visits_status ON visits (status)")
            )
            conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_visits_source_reservation_id ON visits (source_reservation_id)"
                )
            )
            conn.execute(
                text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS uq_visits_tenant_source_reservation "
                    "ON visits (tenant_id, source_reservation_id)"
                )
            )

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

        if not _sqlite_table_has_column(
            conn, "reservation_requests", "converted_visit_id"
        ):
            conn.execute(
                text(
                    "ALTER TABLE reservation_requests ADD COLUMN converted_visit_id INTEGER"
                )
            )
        if not _sqlite_table_has_column(conn, "reservation_requests", "converted_at"):
            conn.execute(
                text(
                    "ALTER TABLE reservation_requests ADD COLUMN converted_at DATETIME"
                )
            )
        if not _sqlite_table_has_column(
            conn, "reservation_requests", "idempotency_key"
        ):
            conn.execute(
                text(
                    "ALTER TABLE reservation_requests ADD COLUMN idempotency_key VARCHAR(120)"
                )
            )

        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_reservation_requests_tenant_id ON reservation_requests (tenant_id)"
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_reservation_requests_created_at ON reservation_requests (created_at)"
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_reservation_requests_requested_dt ON reservation_requests (requested_dt)"
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_reservation_requests_status ON reservation_requests (status)"
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_reservation_requests_converted_visit_id ON reservation_requests (converted_visit_id)"
            )
        )
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
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_reservation_status_events_tenant_id ON reservation_status_events (tenant_id)"
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_reservation_status_events_reservation_id ON reservation_status_events (reservation_id)"
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_reservation_status_events_created_at ON reservation_status_events (created_at)"
            )
        )

        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS visit_status_events (
                    id INTEGER NOT NULL PRIMARY KEY,
                    tenant_id INTEGER NOT NULL,
                    visit_id INTEGER NOT NULL,
                    created_at DATETIME NOT NULL,
                    from_status VARCHAR(32),
                    to_status VARCHAR(32) NOT NULL,
                    actor VARCHAR(120),
                    note VARCHAR(300),
                    FOREIGN KEY(tenant_id) REFERENCES tenants (id),
                    FOREIGN KEY(visit_id) REFERENCES visits (id)
                )
                """
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_visit_status_events_tenant_id ON visit_status_events (tenant_id)"
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_visit_status_events_visit_id ON visit_status_events (visit_id)"
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_visit_status_events_created_at ON visit_status_events (created_at)"
            )
        )

        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS employee_availability_days (
                    id INTEGER NOT NULL PRIMARY KEY,
                    tenant_id INTEGER NOT NULL,
                    employee_name VARCHAR(120) NOT NULL,
                    day DATE NOT NULL,
                    is_day_off BOOLEAN NOT NULL DEFAULT 0,
                    start_hour INTEGER,
                    end_hour INTEGER,
                    note VARCHAR(300),
                    FOREIGN KEY(tenant_id) REFERENCES tenants (id)
                )
                """
            )
        )
        conn.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_availability_tenant_employee_day "
                "ON employee_availability_days (tenant_id, employee_name, day)"
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_employee_availability_days_tenant_id ON employee_availability_days (tenant_id)"
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_employee_availability_days_employee_name ON employee_availability_days (employee_name)"
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_employee_availability_days_day ON employee_availability_days (day)"
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_employee_availability_days_is_day_off ON employee_availability_days (is_day_off)"
            )
        )

        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS employee_blocks (
                    id INTEGER NOT NULL PRIMARY KEY,
                    tenant_id INTEGER NOT NULL,
                    employee_name VARCHAR(120) NOT NULL,
                    start_dt DATETIME NOT NULL,
                    end_dt DATETIME NOT NULL,
                    reason VARCHAR(300),
                    created_at DATETIME NOT NULL,
                    FOREIGN KEY(tenant_id) REFERENCES tenants (id)
                )
                """
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_employee_blocks_tenant_id ON employee_blocks (tenant_id)"
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_employee_blocks_employee_name ON employee_blocks (employee_name)"
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_employee_blocks_start_dt ON employee_blocks (start_dt)"
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_employee_blocks_end_dt ON employee_blocks (end_dt)"
            )
        )

        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS employee_weekly_schedules (
                    id INTEGER NOT NULL PRIMARY KEY,
                    tenant_id INTEGER NOT NULL,
                    employee_id INTEGER NOT NULL,
                    weekday INTEGER NOT NULL,
                    is_day_off BOOLEAN NOT NULL DEFAULT 0,
                    start_hour INTEGER,
                    end_hour INTEGER,
                    FOREIGN KEY(tenant_id) REFERENCES tenants (id),
                    FOREIGN KEY(employee_id) REFERENCES employees (id)
                )
                """
            )
        )
        conn.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_employee_weekly_schedule "
                "ON employee_weekly_schedules (tenant_id, employee_id, weekday)"
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_employee_weekly_schedules_tenant_id ON employee_weekly_schedules (tenant_id)"
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_employee_weekly_schedules_employee_id ON employee_weekly_schedules (employee_id)"
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_employee_weekly_schedules_weekday ON employee_weekly_schedules (weekday)"
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_employee_weekly_schedules_is_day_off ON employee_weekly_schedules (is_day_off)"
            )
        )

        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS employee_service_capabilities (
                    id INTEGER NOT NULL PRIMARY KEY,
                    tenant_id INTEGER NOT NULL,
                    employee_id INTEGER NOT NULL,
                    service_name VARCHAR(120) NOT NULL,
                    duration_min INTEGER,
                    price_override NUMERIC(10,2),
                    is_active BOOLEAN NOT NULL DEFAULT 1,
                    created_at DATETIME NOT NULL,
                    updated_at DATETIME NOT NULL,
                    FOREIGN KEY(tenant_id) REFERENCES tenants (id),
                    FOREIGN KEY(employee_id) REFERENCES employees (id)
                )
                """
            )
        )
        conn.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_employee_service_capability "
                "ON employee_service_capabilities (tenant_id, employee_id, service_name)"
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_employee_service_capabilities_tenant_id ON employee_service_capabilities (tenant_id)"
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_employee_service_capabilities_employee_id ON employee_service_capabilities (employee_id)"
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_employee_service_capabilities_service_name ON employee_service_capabilities (service_name)"
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_employee_service_capabilities_is_active ON employee_service_capabilities (is_active)"
            )
        )

        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS employee_leave_requests (
                    id INTEGER NOT NULL PRIMARY KEY,
                    tenant_id INTEGER NOT NULL,
                    employee_id INTEGER NOT NULL,
                    start_day DATE NOT NULL,
                    end_day DATE NOT NULL,
                    status VARCHAR(20) NOT NULL DEFAULT 'pending',
                    reason VARCHAR(500),
                    requested_by VARCHAR(160),
                    decided_by VARCHAR(160),
                    decision_note VARCHAR(500),
                    decided_at DATETIME,
                    created_at DATETIME NOT NULL,
                    updated_at DATETIME NOT NULL,
                    FOREIGN KEY(tenant_id) REFERENCES tenants (id),
                    FOREIGN KEY(employee_id) REFERENCES employees (id)
                )
                """
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_employee_leave_requests_tenant_id ON employee_leave_requests (tenant_id)"
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_employee_leave_requests_employee_id ON employee_leave_requests (employee_id)"
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_employee_leave_requests_status ON employee_leave_requests (status)"
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_employee_leave_requests_start_day ON employee_leave_requests (start_day)"
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_employee_leave_requests_end_day ON employee_leave_requests (end_day)"
            )
        )

        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS shift_swap_requests (
                    id INTEGER NOT NULL PRIMARY KEY,
                    tenant_id INTEGER NOT NULL,
                    shift_day DATE NOT NULL,
                    from_employee_id INTEGER NOT NULL,
                    to_employee_id INTEGER NOT NULL,
                    from_start_hour INTEGER NOT NULL DEFAULT 9,
                    from_end_hour INTEGER NOT NULL DEFAULT 18,
                    to_start_hour INTEGER NOT NULL DEFAULT 9,
                    to_end_hour INTEGER NOT NULL DEFAULT 18,
                    status VARCHAR(20) NOT NULL DEFAULT 'pending',
                    reason VARCHAR(500),
                    requested_by VARCHAR(160),
                    decided_by VARCHAR(160),
                    decision_note VARCHAR(500),
                    decided_at DATETIME,
                    created_at DATETIME NOT NULL,
                    updated_at DATETIME NOT NULL,
                    FOREIGN KEY(tenant_id) REFERENCES tenants (id),
                    FOREIGN KEY(from_employee_id) REFERENCES employees (id),
                    FOREIGN KEY(to_employee_id) REFERENCES employees (id)
                )
                """
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_shift_swap_requests_tenant_id ON shift_swap_requests (tenant_id)"
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_shift_swap_requests_shift_day ON shift_swap_requests (shift_day)"
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_shift_swap_requests_status ON shift_swap_requests (status)"
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_shift_swap_requests_from_employee_id ON shift_swap_requests (from_employee_id)"
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_shift_swap_requests_to_employee_id ON shift_swap_requests (to_employee_id)"
            )
        )

        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS time_clock_entries (
                    id INTEGER NOT NULL PRIMARY KEY,
                    tenant_id INTEGER NOT NULL,
                    employee_id INTEGER NOT NULL,
                    event_type VARCHAR(20) NOT NULL,
                    event_dt DATETIME NOT NULL,
                    source VARCHAR(80),
                    note VARCHAR(300),
                    created_at DATETIME NOT NULL,
                    FOREIGN KEY(tenant_id) REFERENCES tenants (id),
                    FOREIGN KEY(employee_id) REFERENCES employees (id)
                )
                """
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_time_clock_entries_tenant_id ON time_clock_entries (tenant_id)"
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_time_clock_entries_employee_id ON time_clock_entries (employee_id)"
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_time_clock_entries_event_type ON time_clock_entries (event_type)"
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_time_clock_entries_event_dt ON time_clock_entries (event_dt)"
            )
        )

        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS schedule_audit_events (
                    id INTEGER NOT NULL PRIMARY KEY,
                    tenant_id INTEGER NOT NULL,
                    action VARCHAR(80) NOT NULL,
                    actor_email VARCHAR(160),
                    employee_id INTEGER,
                    related_id VARCHAR(120),
                    payload_json TEXT,
                    created_at DATETIME NOT NULL,
                    FOREIGN KEY(tenant_id) REFERENCES tenants (id),
                    FOREIGN KEY(employee_id) REFERENCES employees (id)
                )
                """
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_schedule_audit_events_tenant_id ON schedule_audit_events (tenant_id)"
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_schedule_audit_events_action ON schedule_audit_events (action)"
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_schedule_audit_events_actor_email ON schedule_audit_events (actor_email)"
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_schedule_audit_events_employee_id ON schedule_audit_events (employee_id)"
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_schedule_audit_events_related_id ON schedule_audit_events (related_id)"
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_schedule_audit_events_created_at ON schedule_audit_events (created_at)"
            )
        )

        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS schedule_notifications (
                    id INTEGER NOT NULL PRIMARY KEY,
                    tenant_id INTEGER NOT NULL,
                    employee_id INTEGER,
                    event_type VARCHAR(80) NOT NULL,
                    message VARCHAR(500) NOT NULL,
                    channel VARCHAR(32) NOT NULL DEFAULT 'internal',
                    status VARCHAR(20) NOT NULL DEFAULT 'pending',
                    last_error VARCHAR(500),
                    sent_at DATETIME,
                    created_at DATETIME NOT NULL,
                    updated_at DATETIME NOT NULL,
                    FOREIGN KEY(tenant_id) REFERENCES tenants (id),
                    FOREIGN KEY(employee_id) REFERENCES employees (id)
                )
                """
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_schedule_notifications_tenant_id ON schedule_notifications (tenant_id)"
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_schedule_notifications_employee_id ON schedule_notifications (employee_id)"
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_schedule_notifications_event_type ON schedule_notifications (event_type)"
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_schedule_notifications_channel ON schedule_notifications (channel)"
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_schedule_notifications_status ON schedule_notifications (status)"
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_schedule_notifications_sent_at ON schedule_notifications (sent_at)"
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_schedule_notifications_created_at ON schedule_notifications (created_at)"
            )
        )

        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS service_buffers (
                    id INTEGER NOT NULL PRIMARY KEY,
                    tenant_id INTEGER NOT NULL,
                    service_name VARCHAR(120) NOT NULL,
                    before_min INTEGER NOT NULL DEFAULT 0,
                    after_min INTEGER NOT NULL DEFAULT 0,
                    FOREIGN KEY(tenant_id) REFERENCES tenants (id)
                )
                """
            )
        )
        conn.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_service_buffer_tenant_service "
                "ON service_buffers (tenant_id, service_name)"
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_service_buffers_tenant_id ON service_buffers (tenant_id)"
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_service_buffers_service_name ON service_buffers (service_name)"
            )
        )

        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS employee_buffers (
                    id INTEGER NOT NULL PRIMARY KEY,
                    tenant_id INTEGER NOT NULL,
                    employee_name VARCHAR(120) NOT NULL,
                    before_min INTEGER NOT NULL DEFAULT 0,
                    after_min INTEGER NOT NULL DEFAULT 0,
                    FOREIGN KEY(tenant_id) REFERENCES tenants (id)
                )
                """
            )
        )
        conn.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_employee_buffer_tenant_employee "
                "ON employee_buffers (tenant_id, employee_name)"
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_employee_buffers_tenant_id ON employee_buffers (tenant_id)"
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_employee_buffers_employee_name ON employee_buffers (employee_name)"
            )
        )

        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS client_notes (
                    id INTEGER NOT NULL PRIMARY KEY,
                    tenant_id INTEGER NOT NULL,
                    client_id INTEGER NOT NULL,
                    note VARCHAR(600) NOT NULL,
                    actor VARCHAR(120),
                    created_at DATETIME NOT NULL,
                    FOREIGN KEY(tenant_id) REFERENCES tenants (id),
                    FOREIGN KEY(client_id) REFERENCES clients (id)
                )
                """
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_client_notes_tenant_id ON client_notes (tenant_id)"
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_client_notes_client_id ON client_notes (client_id)"
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_client_notes_created_at ON client_notes (created_at)"
            )
        )

        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS reservation_rate_limit_events (
                    id INTEGER NOT NULL PRIMARY KEY,
                    tenant_id INTEGER NOT NULL,
                    created_at DATETIME NOT NULL,
                    client_ip VARCHAR(64),
                    phone VARCHAR(40),
                    FOREIGN KEY(tenant_id) REFERENCES tenants (id)
                )
                """
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_rrl_events_tenant_id ON reservation_rate_limit_events (tenant_id)"
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_rrl_events_created_at ON reservation_rate_limit_events (created_at)"
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_rrl_events_client_ip ON reservation_rate_limit_events (client_ip)"
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_rrl_events_phone ON reservation_rate_limit_events (phone)"
            )
        )


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
