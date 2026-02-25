[tool.vulture]
exclude = ["venv", ".venv", "tests"]
ignore_names = ["Config", "model_config"] # Pydantic internals
