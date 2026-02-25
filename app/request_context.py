from contextvars import ContextVar

actor_email_ctx: ContextVar[str | None] = ContextVar("actor_email_ctx", default=None)
actor_role_ctx: ContextVar[str | None] = ContextVar("actor_role_ctx", default=None)
tenant_slug_ctx: ContextVar[str | None] = ContextVar("tenant_slug_ctx", default=None)
