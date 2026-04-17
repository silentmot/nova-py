# PowerShell dev runner — equivalent of run_dev.sh for Windows users.

$ErrorActionPreference = "Stop"

Set-Location (Join-Path $PSScriptRoot "..")

$venvActivate = ".\.venv\Scripts\Activate.ps1"
if (Test-Path $venvActivate) {
    & $venvActivate
}

if (Test-Path ".env") {
    Get-Content .env | ForEach-Object {
        if ($_ -match "^\s*#") { return }
        if ($_ -match "^\s*$") { return }
        $pair = $_ -split "=", 2
        if ($pair.Count -eq 2) {
            [Environment]::SetEnvironmentVariable($pair[0].Trim(), $pair[1].Trim(), "Process")
        }
    }
}

python -m nova @args
