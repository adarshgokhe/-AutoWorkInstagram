# AnimeNova - Setup Automatic Startup
# Run this script once to configure AnimeNova to launch silently on laptop boot/login.

$startupFolder = [System.IO.Path]::Combine($env:APPDATA, "Microsoft\Windows\Start Menu\Programs\Startup")
$vbsPath = [System.IO.Path]::Combine($startupFolder, "AnimeNovaStartup.vbs")
$scriptPath = "c:\Users\coool\AnimeNova_FULL_WORKING_SAFE\launch_and_keep_alive.ps1"

if (!(Test-Path $scriptPath)) {
    throw "Keep-alive script not found: $scriptPath"
}

$vbsContent = @"
Set WshShell = CreateObject("WScript.Shell")
WshShell.Run "powershell.exe -ExecutionPolicy Bypass -File `"$scriptPath`" -NoBrowser", 0, False
"@

try {
    [System.IO.File]::WriteAllText($vbsPath, $vbsContent)
    Write-Host ""
    Write-Host "==================================================" -ForegroundColor Green
    Write-Host " SUCCESS: AUTOMATIC STARTUP CONFIGURED!" -ForegroundColor Green
    Write-Host "==================================================" -ForegroundColor Green
    Write-Host "VBS runner created: $vbsPath"
    Write-Host "When you turn on or open your laptop and log in, the"
    Write-Host "AnimeNova backend + Cloudflare tunnel will run silently"
    Write-Host "in the background and start posting."
    Write-Host "==================================================" -ForegroundColor Green
    Write-Host ""
} catch {
    Write-Host "Error writing startup script: $_" -ForegroundColor Red
}
