param([string]$OutputDirectory = '')
$ErrorActionPreference = 'Stop'
$taskOwnedWorkCreated = $false
Push-Location -LiteralPath $PSScriptRoot
try {
    $taskBuildStamp = (Get-Date -Format 'yyyyMMdd-HHmmss') + '-' + [Guid]::NewGuid().ToString('N').Substring(0,8)
    $taskBuildCache = Join-Path $env:LOCALAPPDATA 'MokkaECULab\Development\v0.2.14'
    if (-not $OutputDirectory) {
        # Candidate outputs stay outside checkout/OneDrive; existing release contents are untouched.
        $taskCandidates = Join-Path $taskBuildCache 'Candidates'
        $taskExisting = @(Get-ChildItem -LiteralPath $taskCandidates -Directory -ErrorAction SilentlyContinue)
        if ($taskExisting.Count -ge 3) { throw 'Three candidates already exist. Review/archive them explicitly before another default build; nothing was deleted.' }
        $OutputDirectory = Join-Path $taskCandidates ('candidate-' + $taskBuildStamp)
    }
    if (Test-Path -LiteralPath $OutputDirectory) { throw 'Choose a fresh candidate folder; no existing build will be overwritten.' }
    $taskWorkRoot = Join-Path $taskBuildCache 'TemporaryBuilds'
    $taskBuildWork = Join-Path $taskWorkRoot ([Guid]::NewGuid().ToString('N'))
    if (Test-Path -LiteralPath $taskBuildWork) { throw 'Fresh temporary build path required.' }
    New-Item -ItemType Directory -Path $taskWorkRoot -Force | Out-Null
    New-Item -ItemType Directory -Path $taskBuildWork | Out-Null
    $taskOwnedWorkCreated = $true
    & '.\.venv\Scripts\python.exe' -m PyInstaller --noconfirm --workpath (Join-Path $taskBuildWork 'launcher') --distpath (Join-Path $taskBuildWork 'launcher-dist') MokkaLauncher.spec
    if ($LASTEXITCODE -ne 0) { throw 'Stable launcher build failed' }
    & '.\.venv\Scripts\python.exe' -m PyInstaller --noconfirm --workpath $taskBuildWork --distpath $OutputDirectory MokkaECULab.spec
    if ($LASTEXITCODE -ne 0) { throw 'PyInstaller build failed' }
    $taskEmbeddedLauncher = Join-Path $OutputDirectory 'MokkaECULab\_internal\launcher'
    New-Item -ItemType Directory -Path $taskEmbeddedLauncher | Out-Null
    Copy-Item -LiteralPath (Join-Path $taskBuildWork 'launcher-dist\MokkaECULabLauncher.exe') -Destination $taskEmbeddedLauncher
    Write-Output (Join-Path $OutputDirectory 'MokkaECULab\MokkaECULab.exe')
} finally {
    # Only this invocation's fresh temporary tree is removable, never an old candidate/data folder.
    if ($taskOwnedWorkCreated -and $taskBuildWork -and (Test-Path -LiteralPath $taskBuildWork)) {
        $taskResolvedWork = (Resolve-Path -LiteralPath $taskBuildWork).Path
        $taskResolvedParent = (Resolve-Path -LiteralPath $taskWorkRoot).Path.TrimEnd('\')
        if ([IO.Path]::GetDirectoryName($taskResolvedWork) -ne $taskResolvedParent -or [IO.Path]::GetFileName($taskResolvedWork) -notmatch '^[a-f0-9]{32}$') { throw 'Temporary cleanup boundary failed; preserved for review.' }
        Remove-Item -LiteralPath $taskResolvedWork -Recurse -Force
    }
    Pop-Location
}
