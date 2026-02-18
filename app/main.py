from fastapi import FastAPI

from .api import public_router, router
from .db import Base, engine, run_schema_migrations

run_schema_migrations()
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="SalonOS",
    description="Telegram-driven salon management API",
    version="1.0.0",
)


@app.get("/ping")
def ping():
    return {"ok": True}


app.include_router(router)
app.include_router(public_router)
