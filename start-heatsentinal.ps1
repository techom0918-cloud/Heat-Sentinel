<#
    HeatSentinal - one-command start.

    Opens the backend and the static server in their OWN windows so neither
    can be killed by running other commands, waits until the API actually
    answers, then opens the browser. Run this instead of starting the two
    servers by hand.

    Usage:  right-click -> Run with PowerShell
        or: powershell -ExecutionPolicy Bypass -File .\start-heatsentinal.ps1
#>

$ErrorActionPreference = 'Stop'
$Root     = 'C:\dev\HeatSentinal'
$Backend  = Join-Path $Root 'backend'
$Frontend = Join-Path $Root 'frontend'
$ApiPort  = 8000
$WebPort  = 5500

Write-Host ''
Write-Host '  HeatSentinal' -ForegroundColor Magenta
Write-Host '  ------------' -ForegroundColor DarkGray

# --- preflight ------------------------------------------------------------
foreach ($p in @($Backend, $Frontend)) {
    if (-not (Test-Path $p)) { Write-Host "  MISSING: $p" -ForegroundColor Red; pause; exit 1 }
}
if (-not (Test-Path (Join-Path $Backend '.venv\Scripts\Activate.ps1'))) {
    Write-Host '  MISSING: backend\.venv - create it first' -ForegroundColor Red; pause; exit 1
}
if (-not (Test-Path (Join-Path $Frontend 'js\pages\transparency.js'))) {
    Write-Host '  WARNING: frontend looks like an older build' -ForegroundColor Yellow
}

$model = Join-Path $Root 'ml\heat_model.joblib'
if (Test-Path $model) {
    Write-Host "  model      OK  ($([math]::Round((Get-Item $model).Length/1MB,1)) MB)" -ForegroundColor Green
} else {
    Write-Host '  model      MISSING - ML pages will report 503' -ForegroundColor Yellow
}

# --- free the ports if something is already holding them ------------------
foreach ($port in @($ApiPort, $WebPort)) {
    $held = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    foreach ($c in $held) {
        try {
            Stop-Process -Id $c.OwningProcess -Force -ErrorAction Stop
            Write-Host "  port $port   freed (killed PID $($c.OwningProcess))" -ForegroundColor DarkGray
        } catch { }
    }
}

# --- launch, each in its own window ---------------------------------------
Start-Process powershell -ArgumentList @(
    '-NoExit', '-Command',
    "`$host.UI.RawUI.WindowTitle='HeatSentinal API'; Set-Location '$Backend'; " +
    ".\.venv\Scripts\Activate.ps1; uvicorn app.main:app --reload --port $ApiPort"
)

Start-Process powershell -ArgumentList @(
    '-NoExit', '-Command',
    "`$host.UI.RawUI.WindowTitle='HeatSentinal Web'; Set-Location '$Frontend'; " +
    "python -m http.server $WebPort --bind 127.0.0.1"
)

# --- wait for the API to actually answer ----------------------------------
Write-Host -NoNewline '  api        starting'
$ok = $false
foreach ($i in 1..40) {
    Start-Sleep -Milliseconds 750
    try {
        $r = Invoke-WebRequest "http://127.0.0.1:$ApiPort/api/v1/health" -TimeoutSec 3 -UseBasicParsing
        if ($r.StatusCode -eq 200) { $ok = $true; break }
    } catch { Write-Host -NoNewline '.' }
}
Write-Host ''

if ($ok) {
    Write-Host "  api        http://127.0.0.1:$ApiPort  ready" -ForegroundColor Green
    try {
        $m = Invoke-RestMethod "http://127.0.0.1:$ApiPort/api/v1/risk/model" -TimeoutSec 5
        if ($m.available) { Write-Host '  ml model   loaded' -ForegroundColor Green }
        else { Write-Host '  ml model   NOT loaded' -ForegroundColor Yellow }
    } catch { }
} else {
    Write-Host '  api        did not come up - check the API window' -ForegroundColor Red
}

Write-Host "  web        http://127.0.0.1:$WebPort" -ForegroundColor Green
Write-Host ''
Write-Host '  Keep both windows open. Run other commands in a THIRD window.' -ForegroundColor DarkGray
Write-Host ''

Start-Sleep -Seconds 1
Start-Process "http://127.0.0.1:$WebPort"
