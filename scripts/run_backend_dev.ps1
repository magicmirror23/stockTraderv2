param(
  [switch]$NoReload
)

$repoRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repoRoot ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $python)) {
  throw "Virtual environment python not found at $python"
}

$args = @(
  "-m", "uvicorn",
  "backend.api.main:app",
  "--host", "0.0.0.0",
  "--port", "8000"
)

if (-not $NoReload) {
  $args += @(
    "--reload",
    "--reload-dir", "backend",
    "--reload-exclude", ".venv/*",
    "--reload-exclude", "storage/*",
    "--reload-exclude", "models/artifacts/*",
    "--reload-exclude", "frontend/dist/*"
  )
}

& $python @args
