$projectRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $projectRoot

$env:PYTHONPATH = $projectRoot.Path
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"

Write-Host "Starting frontend"
Write-Host "Project root: $projectRoot"
& $python -m streamlit run frontend/streamlit_app.py
