param([string]$OutputDirectory = '')
$ErrorActionPreference = 'Stop'
Push-Location -LiteralPath $PSScriptRoot
try {
    $taskBuildStamp = Get-Date -Format 'yyyyMMdd-HHmmss'
    if (-not $OutputDirectory) {
        # Fresh output avoids overwriting a running executable or OneDrive placeholders.
        $OutputDirectory = Join-Path $PSScriptRoot ('release\' + $taskBuildStamp)
    }
    $taskBuildWork = Join-Path $env:LOCALAPPDATA ('MokkaECULab\build-cache\' + $taskBuildStamp)
    & '.\.venv\Scripts\python.exe' -m PyInstaller --noconfirm --workpath $taskBuildWork --distpath $OutputDirectory MokkaECULab.spec
    if ($LASTEXITCODE -ne 0) { throw 'PyInstaller build failed' }
    Write-Output (Join-Path $OutputDirectory 'MokkaECULab\MokkaECULab.exe')
} finally { Pop-Location }
