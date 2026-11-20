$ErrorActionPreference = 'Stop'
Push-Location -LiteralPath (Split-Path -Parent $PSScriptRoot)
try {
    docker compose config --quiet
    if ($LASTEXITCODE -ne 0) { throw 'Compose configuration or Docker CLI is unavailable.' }
    docker compose up --build --detach --wait --wait-timeout 300
    if ($LASTEXITCODE -ne 0) { throw 'Stack startup failed. Run docker compose ps and docker compose logs.' }
    $port = if ($env:WEB_PORT) { $env:WEB_PORT } else { 5173 }
    Write-Host "Stack started. Dashboard http://localhost:$port"
} finally { Pop-Location }
