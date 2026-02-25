from sqlalchemy import inspect
from app.db import engine

def generate_schema_report():
    print("--- Database Schema Report ---")
    inspector = inspect(engine)
    
    for table_name in inspector.get_table_names():
        print(f"
Table: {table_name}")
        for column in inspector.get_columns(table_name):
            pk = " (PK)" if column['primary_key'] else ""
            fk = "" # Inspecting FKs requires more logic
            print(f"  - {column['name']}: {column['type']}{pk}")

if __name__ == "__main__":
    generate_schema_report()
