import json
from app.main import app

def generate_docs():
    openapi_schema = app.openapi()
    
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
    <title>SalonOS API Docs</title>
    <meta charset="utf-8"/>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <link rel="stylesheet" href="https://unpkg.com/swagger-ui-dist@5/swagger-ui.css" />
    </head>
    <body>
    <div id="swagger-ui"></div>
    <script src="https://unpkg.com/swagger-ui-dist@5/swagger-ui-bundle.js"></script>
    <script>
    window.onload = () => {{
      const spec = {json.dumps(openapi_schema)};
      window.ui = SwaggerUIBundle({{
        spec: spec,
        dom_id: '#swagger-ui',
      }});
    }};
    </script>
    </body>
    </html>
    """
    
    with open("docs/api_reference_offline.html", "w", encoding="utf-8") as f:
        f.write(html)
    print("Documentation generated: docs/api_reference_offline.html")

if __name__ == "__main__":
    generate_docs()
