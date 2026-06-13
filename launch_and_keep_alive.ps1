
# AnimeNova - Keep-Alive Launcher
# Run this script ONCE and leave the window open. It keeps backend + Cloudflare tunnel alive.
# Press Ctrl+C to stop.

param([switch]$NoBrowser)

$root        = Split-Path -Parent $MyInvocation.MyCommand.Path
$backend     = Join-Path $root "backend"
$python      = Join-Path $backend "venv\Scripts\python.exe"
$cloudflared = "C:\Program Files (x86)\cloudflared\cloudflared.exe"
$cfLog       = Join-Path $backend "cloudflared.log"
$envPath     = Join-Path $backend ".env"

if (!(Test-Path $python))      { throw "Python venv not found: $python" }
if (!(Test-Path $cloudflared)) { throw "cloudflared not found: $cloudflared" }

function Start-Backend {
    $portPids = netstat -ano | Select-String ':8000' | ForEach-Object { ($_ -split '\s+')[-1] } | Sort-Object -Unique
    foreach ($p in $portPids) { if ($p -match '^\d+$' -and [int]$p -ne 0) { Stop-Process -Id ([int]$p) -Force -ErrorAction SilentlyContinue } }
    $proc = Start-Process -FilePath $python -ArgumentList @("-m","uvicorn","main:app","--host","127.0.0.1","--port","8000") -WorkingDirectory $backend -WindowStyle Hidden -PassThru
    Write-Host "[$(Get-Date -f 'HH:mm:ss')] Backend started (PID $($proc.Id))"
    return $proc
}

function Start-Tunnel {
    Get-Process -Name "cloudflared" -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 1
    Remove-Item -LiteralPath $cfLog -Force -ErrorAction SilentlyContinue
    $proc = Start-Process -FilePath $cloudflared -ArgumentList @("tunnel","--url","http://127.0.0.1:8000","--edge-ip-version","4","--protocol","http2","--logfile",$cfLog) -WindowStyle Hidden -PassThru
    Write-Host "[$(Get-Date -f 'HH:mm:ss')] Cloudflared started (PID $($proc.Id))"

    $url = ""
    $deadline = (Get-Date).AddSeconds(45)
    while ((Get-Date) -lt $deadline -and -not $url) {
        Start-Sleep -Seconds 2
        if (Test-Path $cfLog) {
            $text = Get-Content $cfLog -Raw -ErrorAction SilentlyContinue
            $m = [regex]::Match($text, 'https://[a-z0-9-]+\.trycloudflare\.com')
            if ($m.Success) { $url = $m.Value }
        }
    }
    return @{ Process = $proc; Url = $url }
}

function Update-EnvUrl($url) {
    $mediaUrl = "$url/api/media/output"
    $text = Get-Content $envPath -Raw
    $text = [regex]::Replace($text, '(?m)^PUBLIC_MEDIA_BASE_URL=.*$', "PUBLIC_MEDIA_BASE_URL=$mediaUrl")
    [System.IO.File]::WriteAllText($envPath, $text, [System.Text.UTF8Encoding]::new($false))
    Write-Host "[$(Get-Date -f 'HH:mm:ss')] .env updated => $mediaUrl"
}

function Restart-Backend {
    $portPids = netstat -ano | Select-String ':8000' | ForEach-Object { ($_ -split '\s+')[-1] } | Sort-Object -Unique
    foreach ($p in $portPids) { if ($p -match '^\d+$' -and [int]$p -ne 0) { Stop-Process -Id ([int]$p) -Force -ErrorAction SilentlyContinue } }
    Start-Sleep -Seconds 1
    $proc = Start-Process -FilePath $python -ArgumentList @("-m","uvicorn","main:app","--host","127.0.0.1","--port","8000") -WorkingDirectory $backend -WindowStyle Hidden -PassThru
    Write-Host "[$(Get-Date -f 'HH:mm:ss')] Backend restarted (PID $($proc.Id))"
    return $proc
}

Write-Host ""
Write-Host "=== AnimeNova Keep-Alive Launcher ===" -ForegroundColor Cyan
Write-Host "Starting all services..."
Write-Host ""

# Initial start
$beProc = Start-Backend
Start-Sleep -Seconds 5
$cfResult = Start-Tunnel
$cfProc = $cfResult.Process
$cfUrl = $cfResult.Url

if ($cfUrl) {
    Write-Host ""
    Write-Host "=== SERVICES RUNNING ===" -ForegroundColor Green
    Write-Host "  Dashboard:        http://127.0.0.1:8000/app" -ForegroundColor White
    Write-Host "  Webhook URL:      $cfUrl/webhook/instagram" -ForegroundColor Yellow
    Write-Host "  Verify Token:     anime-nova-local-verify" -ForegroundColor White
    Write-Host ""
    Write-Host "IMPORTANT: Register this webhook URL in Meta Developer Console!" -ForegroundColor Red
    Write-Host "  Go to: https://developers.facebook.com/apps -> Webhooks -> Instagram" -ForegroundColor White
    Write-Host "  Callback URL: $cfUrl/webhook/instagram" -ForegroundColor Yellow
    Write-Host "  Verify Token: anime-nova-local-verify" -ForegroundColor White
    Write-Host ""

    Update-EnvUrl $cfUrl

    # Restart backend so it picks up new URL
    Start-Sleep -Seconds 2
    $beProc = Restart-Backend
    Start-Sleep -Seconds 3

    if (-not $NoBrowser) {
        Start-Process -FilePath "msedge.exe" -ArgumentList "http://127.0.0.1:8000/app" -ErrorAction SilentlyContinue
    }
} else {
    Write-Host "WARNING: Could not get Cloudflare URL. Check cloudflared.log" -ForegroundColor Red
}

Write-Host ""
Write-Host "Watchdog loop running. Press Ctrl+C to stop." -ForegroundColor Gray
Write-Host ""

# Watchdog loop
$lastUrl = $cfUrl
while ($true) {
    Start-Sleep -Seconds 15

    # Check if backend is alive
    try {
        $null = Invoke-WebRequest -Uri "http://127.0.0.1:8000/" -UseBasicParsing -TimeoutSec 4 -ErrorAction Stop
    } catch {
        Write-Host "[$(Get-Date -f 'HH:mm:ss')] Backend died - restarting..." -ForegroundColor Yellow
        $beProc = Restart-Backend
        Start-Sleep -Seconds 5
    }

    # Check if cloudflared is alive
    if ($cfProc.HasExited) {
        Write-Host "[$(Get-Date -f 'HH:mm:ss')] Cloudflared died - restarting tunnel..." -ForegroundColor Yellow
        $cfResult = Start-Tunnel
        $cfProc = $cfResult.Process
        $newUrl = $cfResult.Url
        if ($newUrl -and $newUrl -ne $lastUrl) {
            Write-Host "[$(Get-Date -f 'HH:mm:ss')] New tunnel URL: $newUrl/webhook/instagram" -ForegroundColor Cyan
            Update-EnvUrl $newUrl
            $lastUrl = $newUrl
            $beProc = Restart-Backend
            Start-Sleep -Seconds 4
        }
    }
}
