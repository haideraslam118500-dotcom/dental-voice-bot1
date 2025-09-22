param(
  [int]$Lines = 50
)
$ErrorActionPreference = "SilentlyContinue"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location (Join-Path $root "..")
Write-Host "Watching logs/app.log (last $Lines lines) and transcripts/"
if (Test-Path .\logs\app.log) {
  Get-Content .\logs\app.log -Tail $Lines -Wait
} else {
  Write-Host "No log file yet. It will appear after the app writes logs."
}
