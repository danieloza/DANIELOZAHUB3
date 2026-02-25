# Senior IT: Generate dependency map
.\.venv\Scripts\pydeps.exe app --cluster --max-bacon 2 --format svg -o docs/dependencies.svg
Write-Host "Dependency map generated: docs/dependencies.svg"
