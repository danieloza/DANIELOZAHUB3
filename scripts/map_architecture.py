def generate_mermaid():
    diagram = """
    graph TD
    Client[Client (Browser/Telegram)] -->|HTTPS| Cloudflare[Cloudflare/Nginx]
    Cloudflare -->|Reverse Proxy| Uvicorn[Uvicorn Worker]
    Uvicorn -->|ASGI| FastAPI[FastAPI App]
    FastAPI -->|Middleware| RateLimiter
    FastAPI -->|Middleware| Honeypot
    FastAPI -->|Middleware| Auth
    
    FastAPI -->|SQLAlchemy| SQLite[(SQLite DB)]
    FastAPI -->|Log| Structlog[JSON Logs]
    
    Bot[Telegram Bot] -->|Polling| TelegramAPI
    Bot -->|Internal API| FastAPI
    """
    with open("docs/architecture.mermaid", "w") as f:
        f.write(diagram)
    print("Diagram generated: docs/architecture.mermaid")

if __name__ == "__main__":
    generate_mermaid()
