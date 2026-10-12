param([string]$DataDir = "")
$ErrorActionPreference = 'Stop'
$taskRoot = $PSScriptRoot
$taskPython = Join-Path $taskRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $taskPython)) {
    throw 'Set up Python first: see README.md. The project .venv was not found.'
}
Push-Location -LiteralPath $taskRoot
try {
    if ($DataDir) { & $taskPython -m mokka_ecu_lab --data-dir $DataDir }
    else { & $taskPython -m mokka_ecu_lab }
} finally { Pop-Location }
