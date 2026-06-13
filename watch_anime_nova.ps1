param(
    [int]$IntervalSeconds = 60
)

$ErrorActionPreference = "Continue"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$startScript = Join-Path $root "start_anime_nova.ps1"
$backend = Join-Path $root "backend"
$python = Join-Path $backend "venv\Scripts\python.exe"
$envPath = Join-Path $root "backend\.env"
$logPath = Join-Path $root "backend\watchdog.log"
$mutex = [System.Threading.Mutex]::new($false, "AnimeNovaWatchdog")

if (-not $mutex.WaitOne(0, $false)) {
    exit 0
}

function Write-WatchdogLog([string]$message) {
    $line = "$(Get-Date -Format s) $message"
    Add-Content -LiteralPath $logPath -Value $line -Encoding utf8
}

function Test-Url([string]$url, [int]$timeout = 12) {
    try {
        $response = Invoke-RestMethod -Uri $url -TimeoutSec $timeout
        return [bool]$response.ok -or $response.status -eq "ok"
    } catch {
        return $false
    }
}

function Get-PublicHealthUrl {
    if (-not (Test-Path -LiteralPath $envPath)) {
        return ""
    }
    $line = Get-Content -LiteralPath $envPath | Where-Object { $_ -like "PUBLIC_MEDIA_BASE_URL=*" } | Select-Object -First 1
    if (-not $line) {
        return ""
    }
    $mediaUrl = $line.Substring("PUBLIC_MEDIA_BASE_URL=".Length).Trim()
    if ($mediaUrl.EndsWith("/api/media/output")) {
        return $mediaUrl.Substring(0, $mediaUrl.Length - "/api/media/output".Length) + "/health"
    }
    return ""
}

function Restart-BackendPreservingTunnel {
    $portPids = netstat -ano -p tcp | Select-String ':8000' | ForEach-Object { ($_ -split '\s+')[-1] } | Sort-Object -Unique
    foreach ($pidText in $portPids) {
        if ($pidText -match '^\d+$' -and [int]$pidText -ne 0) {
            Stop-Process -Id ([int]$pidText) -Force -ErrorAction SilentlyContinue
        }
    }
    Start-Sleep -Seconds 2
    Start-Process -FilePath $python -ArgumentList @('-m','uvicorn','main:app','--host','127.0.0.1','--port','8000') -WorkingDirectory $backend -WindowStyle Hidden
}

$publicFailures = 0
Write-WatchdogLog "Watchdog started."

try {
    while ($true) {
        $localOk = Test-Url "http://127.0.0.1:8000/health" 8
        $cloudflaredRunning = [bool](Get-Process cloudflared -ErrorAction SilentlyContinue)
        $publicHealth = Get-PublicHealthUrl
        $publicOk = if ($publicHealth) { Test-Url $publicHealth 15 } else { $false }

        if ($publicOk) {
            $publicFailures = 0
        } else {
            $publicFailures += 1
        }

        # Quick-tunnel DNS can be temporarily unavailable from this PC even while
        # Meta can reach it. Restarting on that signal changes the public URL and
        # silently breaks the configured Meta webhook callback.
        if (-not $localOk -and $cloudflaredRunning) {
            Write-WatchdogLog "Restarting backend while preserving the public callback URL."
            Restart-BackendPreservingTunnel
            $publicFailures = 0
            Start-Sleep -Seconds 30
        } elseif (-not $cloudflaredRunning) {
            Write-WatchdogLog "Tunnel process is down; restarting services. local_ok=$localOk public_failures=$publicFailures"
            & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $startScript -NoBrowser
            $publicFailures = 0
            Start-Sleep -Seconds 30
        } elseif ($publicFailures -eq 3 -or ($publicFailures -gt 3 -and $publicFailures % 30 -eq 0)) {
            Write-WatchdogLog "Public health check unavailable, but services remain running to preserve the Meta callback URL. failures=$publicFailures"
        }

        Start-Sleep -Seconds ([Math]::Max(30, $IntervalSeconds))
    }
} finally {
    $mutex.ReleaseMutex()
    $mutex.Dispose()
}
