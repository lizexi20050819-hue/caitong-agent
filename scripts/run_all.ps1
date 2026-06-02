$projectRoot = Resolve-Path (Join-Path $PSScriptRoot "..")

Start-Process powershell -ArgumentList @(
    "-NoExit",
    "-ExecutionPolicy", "Bypass",
    "-Command",
    "cd `"$projectRoot`"; .\scripts\run_backend.ps1"
)

Start-Sleep -Seconds 2

Start-Process powershell -ArgumentList @(
    "-NoExit",
    "-ExecutionPolicy", "Bypass",
    "-Command",
    "cd `"$projectRoot`"; .\scripts\run_frontend.ps1"
)
