$projectRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$frontendRoot = Join-Path $projectRoot "frontend-vue"

Set-Location $frontendRoot

Write-Host "Starting Vue frontend"
Write-Host "Frontend root: $frontendRoot"
npm run dev
