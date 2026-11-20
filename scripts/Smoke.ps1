$ErrorActionPreference = 'Stop'
Push-Location -LiteralPath (Split-Path -Parent $PSScriptRoot)
try {
    docker compose exec -T api python -m ops.smoke
    if ($LASTEXITCODE -ne 0) { throw 'Smoke failed. See the output above.' }
} finally { Pop-Location }
