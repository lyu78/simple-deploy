$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Join-Path $Root ".venv\Scripts\python.exe"
$SimpleDeploy = Join-Path $Root ".venv\Scripts\simple-deploy.exe"
$WebUiRoot = Join-Path $Root "tools-ci\web-ui"
$WebUiIndex = Join-Path $WebUiRoot "dist\index.html"
$WebUiSourcePaths = @(
    (Join-Path $WebUiRoot "src"),
    (Join-Path $WebUiRoot "package.json"),
    (Join-Path $WebUiRoot "package-lock.json"),
    (Join-Path $WebUiRoot "vite.config.ts"),
    (Join-Path $WebUiRoot "tsconfig.json"),
    (Join-Path $WebUiRoot "tsconfig.app.json")
)

$WebHostName = if ([string]::IsNullOrWhiteSpace($env:SIMPLE_DEPLOY_WEB_HOST)) {
    "127.0.0.1"
} else {
    $env:SIMPLE_DEPLOY_WEB_HOST
}

$WebPort = if ([string]::IsNullOrWhiteSpace($env:SIMPLE_DEPLOY_WEB_PORT)) {
    "8000"
} else {
    $env:SIMPLE_DEPLOY_WEB_PORT
}

$WorkerPollInterval = if ([string]::IsNullOrWhiteSpace($env:SIMPLE_DEPLOY_WORKER_POLL_INTERVAL)) {
    "2"
} else {
    $env:SIMPLE_DEPLOY_WORKER_POLL_INTERVAL
}

if ($WebPort -notmatch '^\d+$') {
    Write-Host "[ERROR] SIMPLE_DEPLOY_WEB_PORT must be a number: $WebPort"
    exit 1
}

if ($WorkerPollInterval -notmatch '^\d+$') {
    Write-Host "[ERROR] SIMPLE_DEPLOY_WORKER_POLL_INTERVAL must be a number: $WorkerPollInterval"
    exit 1
}

if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
    Write-Host "[ERROR] Python venv not found: `"$Python`""
    Write-Host "Run initial setup from tools-ci\README.MD."
    exit 1
}

if (-not (Test-Path -LiteralPath $SimpleDeploy -PathType Leaf)) {
    Write-Host "[ERROR] simple-deploy CLI not found: `"$SimpleDeploy`""
    Write-Host "Run: `"$Python`" -m pip install --disable-pip-version-check -e . --no-deps"
    exit 1
}

function Get-NewestFileTime {
    param([string[]] $Paths)

    $newest = $null
    foreach ($path in $Paths) {
        if (-not (Test-Path -LiteralPath $path)) {
            continue
        }

        $items = @()
        if (Test-Path -LiteralPath $path -PathType Container) {
            $items = Get-ChildItem -LiteralPath $path -Recurse -File -ErrorAction SilentlyContinue
        } else {
            $items = @(Get-Item -LiteralPath $path)
        }

        foreach ($item in $items) {
            if ($null -eq $newest -or $item.LastWriteTime -gt $newest) {
                $newest = $item.LastWriteTime
            }
        }
    }

    return $newest
}

function Invoke-CheckedCommand {
    param(
        [string] $Executable,
        [string[]] $Arguments,
        [string] $WorkingDirectory,
        [string] $Description
    )

    Write-Host "[RUN] $Description"
    Push-Location -LiteralPath $WorkingDirectory
    try {
        & $Executable @Arguments
        if ($LASTEXITCODE -ne 0) {
            Write-Host "[ERROR] Command failed with exit code $($LASTEXITCODE): $Description"
            exit $LASTEXITCODE
        }
    } finally {
        Pop-Location
    }
}

function Resolve-NpmCommand {
    $npm = Get-Command npm.cmd -ErrorAction SilentlyContinue
    if ($null -ne $npm) {
        return $npm.Source
    }

    $npm = Get-Command npm -ErrorAction SilentlyContinue
    if ($null -ne $npm) {
        return $npm.Source
    }

    return ""
}

function Ensure-WebUiBuild {
    $reason = ""
    if (-not (Test-Path -LiteralPath $WebUiIndex -PathType Leaf)) {
        $reason = "React UI build not found: `"$WebUiIndex`""
    } else {
        $sourceNewest = Get-NewestFileTime -Paths $WebUiSourcePaths
        $distTime = (Get-Item -LiteralPath $WebUiIndex).LastWriteTime
        if ($null -ne $sourceNewest -and $sourceNewest -gt $distTime) {
            $reason = "React UI build is stale: source files are newer than web-ui\dist\index.html"
        }
    }

    if ([string]::IsNullOrWhiteSpace($reason)) {
        return
    }

    Write-Host "[INFO] $reason"
    if ($env:SIMPLE_DEPLOY_SKIP_WEB_UI_BUILD -eq "1") {
        Write-Host "[WARN] SIMPLE_DEPLOY_SKIP_WEB_UI_BUILD=1, web will use legacy fallback if dist is missing."
        Write-Host ""
        return
    }

    $npm = Resolve-NpmCommand
    if ([string]::IsNullOrWhiteSpace($npm)) {
        Write-Host "[ERROR] npm not found. Install Node.js/npm or run with SIMPLE_DEPLOY_SKIP_WEB_UI_BUILD=1."
        exit 1
    }

    $nodeModules = Join-Path $WebUiRoot "node_modules"
    if (-not (Test-Path -LiteralPath $nodeModules -PathType Container)) {
        Invoke-CheckedCommand `
            -Executable $npm `
            -Arguments @("install") `
            -WorkingDirectory $WebUiRoot `
            -Description "npm install in tools-ci\web-ui"
    }

    Invoke-CheckedCommand `
        -Executable $npm `
        -Arguments @("run", "build") `
        -WorkingDirectory $WebUiRoot `
        -Description "npm run build in tools-ci\web-ui"
}

function Test-Contains {
    param(
        [string] $Text,
        [string] $Needle
    )

    if ($null -eq $Text) {
        return $false
    }

    return $Text.IndexOf($Needle, [System.StringComparison]::OrdinalIgnoreCase) -ge 0
}

function Test-SamePath {
    param(
        [string] $Left,
        [string] $Right
    )

    if ([string]::IsNullOrWhiteSpace($Left) -or [string]::IsNullOrWhiteSpace($Right)) {
        return $false
    }

    $leftFullPath = [System.IO.Path]::GetFullPath($Left)
    $rightFullPath = [System.IO.Path]::GetFullPath($Right)
    return [string]::Equals($leftFullPath, $rightFullPath, [System.StringComparison]::OrdinalIgnoreCase)
}

function ConvertTo-CmdQuoted {
    param([string] $Value)

    return '"' + ($Value -replace '"', '\"') + '"'
}

$Processes = Get-CimInstance Win32_Process

$WebProcesses = @(
    $Processes | Where-Object {
        (Test-SamePath $_.ExecutablePath $Python) -and
        (Test-Contains $_.CommandLine "simple_deploy.web.app:app") -and
        (Test-Contains $_.CommandLine "--app-dir tools-ci") -and
        (Test-Contains $_.CommandLine "--host $WebHostName") -and
        (Test-Contains $_.CommandLine "--port $WebPort")
    }
)

$WorkerProcesses = @(
    $Processes | Where-Object {
        (Test-SamePath $_.ExecutablePath $SimpleDeploy) -and
        (Test-Contains $_.CommandLine " worker")
    }
)

$QuotedRoot = ConvertTo-CmdQuoted $Root
$QuotedPython = ConvertTo-CmdQuoted $Python
$QuotedSimpleDeploy = ConvertTo-CmdQuoted $SimpleDeploy

$WebCommand = "cd /d $QuotedRoot && $QuotedPython -m uvicorn simple_deploy.web.app:app --app-dir tools-ci --host $WebHostName --port $WebPort"
$WorkerCommand = "cd /d $QuotedRoot && $QuotedSimpleDeploy worker --poll-interval $WorkerPollInterval"

Write-Host "Starting simple-deploy operator processes..."
Write-Host "Web/API: http://$($WebHostName):$($WebPort)/"
Write-Host "Worker poll interval: $($WorkerPollInterval)s"
Write-Host ""
Ensure-WebUiBuild

function Start-OperatorWindow {
    param(
        [string] $Title,
        [string] $Command,
        [array] $ExistingProcesses
    )

    if ($ExistingProcesses.Count -gt 0) {
        $processIds = ($ExistingProcesses | ForEach-Object { $_.ProcessId }) -join ", "
        Write-Host "[SKIP] $Title already running. PID(s): $processIds"
        return
    }

    if ($env:SIMPLE_DEPLOY_START_DRY_RUN -eq "1") {
        Write-Host "[DRY-RUN] start `"$Title`" cmd /k `"$Command`""
        return
    }

    Start-Process -FilePath "$env:ComSpec" -ArgumentList @("/k", "title $Title && $Command")
    Write-Host "[START] $Title"
}

Start-OperatorWindow -Title "simple-deploy web" -Command $WebCommand -ExistingProcesses $WebProcesses
Start-OperatorWindow -Title "simple-deploy worker" -Command $WorkerCommand -ExistingProcesses $WorkerProcesses

Write-Host ""
Write-Host "Done. Re-running this script starts only missing processes."
