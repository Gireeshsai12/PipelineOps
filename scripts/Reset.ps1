param([switch]$ConfirmReset)
$ErrorActionPreference = 'Stop'
if (-not $ConfirmReset) {
    throw 'Reset deletes the local PostgreSQL, Prometheus and Grafana volumes. Pass -ConfirmReset to proceed.'
}
Push-Location -LiteralPath (Split-Path -Parent $PSScriptRoot)
try {
    docker compose down --volumes --remove-orphans
    if ($LASTEXITCODE -ne 0) { throw 'Reset failed.' }
} finally { Pop-Location }
