$projectRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $projectRoot

# 杀掉所有占用 8001 端口的进程
$pids = (Get-NetTCPConnection -LocalPort 8001 -ErrorAction SilentlyContinue).OwningProcess | Sort-Object -Unique
foreach ($p in $pids) {
    if ($p) {
        Write-Host "Killing PID $p on port 8001"
        Stop-Process -Id $p -Force -ErrorAction SilentlyContinue
    }
}
Start-Sleep -Seconds 1

$env:PYTHONPATH = $projectRoot.Path
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"

Write-Host "Starting backend at http://127.0.0.1:8001"
& $python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8001
