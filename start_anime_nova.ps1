param(
    [switch]$NoBrowser
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$backend = Join-Path $root "backend"
$envPath = Join-Path $backend ".env"
$python = Join-Path $backend "venv\Scripts\python.exe"
$cloudflared = "C:\Program Files (x86)\cloudflared\cloudflared.exe"
$cloudflareLog = Join-Path $backend "cloudflared.log"

if (!(Test-Path $python)) {
    throw "Backend venv python not found: $python"
}
if (!(Test-Path $cloudflared)) {
    throw "cloudflared not found: $cloudflared"
}

Write-Host "Stopping old Anime Nova backend and tunnel..."
$portPids = netstat -ano -p tcp | Select-String ':8000' | ForEach-Object { ($_ -split '\s+')[-1] } | Sort-Object -Unique
foreach ($pidText in $portPids) {
    if ($pidText -match '^\d+$' -and [int]$pidText -ne 0) {
        Stop-Process -Id ([int]$pidText) -Force -ErrorAction SilentlyContinue
    }
}
Get-Process cloudflared -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2

Write-Host "Starting local backend..."
Start-Process -FilePath $python -ArgumentList @('-m','uvicorn','main:app','--host','127.0.0.1','--port','8000','--lifespan','off') -WorkingDirectory $backend -WindowStyle Hidden
Start-Sleep -Seconds 5

Write-Host "Starting public Cloudflare tunnel..."
Remove-Item -LiteralPath $cloudflareLog -Force -ErrorAction SilentlyContinue
Start-Process -FilePath $cloudflared -ArgumentList @('tunnel','--url','http://127.0.0.1:8000','--edge-ip-version','4','--protocol','http2','--logfile',$cloudflareLog) -WindowStyle Hidden

$publicUrl = ""
$deadline = (Get-Date).AddSeconds(45)
while ((Get-Date) -lt $deadline -and -not $publicUrl) {
    Start-Sleep -Seconds 2
    if (Test-Path $cloudflareLog) {
        $text = Get-Content $cloudflareLog -Raw
        $match = [regex]::Match($text, 'https://[a-z0-9-]+\.trycloudflare\.com')
        if ($match.Success) {
            $publicUrl = $match.Value
        }
    }
}
if (-not $publicUrl) {
    throw "Cloudflare did not return a public URL. Check firewall/VPN/network and backend/cloudflared.log."
}

Write-Host "Updating backend .env public URL..."
$envItem = Get-Item -LiteralPath $envPath -Force
$oldEnvAttributes = $envItem.Attributes
$envItem.Attributes = ($oldEnvAttributes -band (-bnot [System.IO.FileAttributes]::ReadOnly) -band (-bnot [System.IO.FileAttributes]::Hidden))
$envText = Get-Content $envPath -Raw
$mediaUrl = "$publicUrl/api/media/output"
if ($envText -match '(?m)^PUBLIC_MEDIA_BASE_URL=') {
    $envText = [regex]::Replace($envText, '(?m)^PUBLIC_MEDIA_BASE_URL=.*$', "PUBLIC_MEDIA_BASE_URL=$mediaUrl")
} else {
    $envText = $envText.TrimEnd() + "`r`nPUBLIC_MEDIA_BASE_URL=$mediaUrl`r`n"
}
[System.IO.File]::WriteAllText($envPath, $envText, [System.Text.UTF8Encoding]::new($false))
(Get-Item -LiteralPath $envPath -Force).Attributes = $oldEnvAttributes

Write-Host "Restarting backend with new public URL..."
$portPids = netstat -ano -p tcp | Select-String ':8000' | ForEach-Object { ($_ -split '\s+')[-1] } | Sort-Object -Unique
foreach ($pidText in $portPids) {
    if ($pidText -match '^\d+$' -and [int]$pidText -ne 0) {
        Stop-Process -Id ([int]$pidText) -Force -ErrorAction SilentlyContinue
    }
}
Start-Sleep -Seconds 2
Start-Process -FilePath $python -ArgumentList @('-m','uvicorn','main:app','--host','127.0.0.1','--port','8000') -WorkingDirectory $backend -WindowStyle Hidden
Start-Sleep -Seconds 5

Write-Host ""
Write-Host "Anime Nova is running:"
Write-Host "Dashboard: http://127.0.0.1:8000/app"
Write-Host "Public webhook callback URL: $publicUrl/webhook/instagram"
Write-Host "Verify token: anime-nova-local-verify"
Write-Host ""
if (-not $NoBrowser) {
    Start-Process -FilePath msedge.exe -ArgumentList 'http://127.0.0.1:8000/app'
}
