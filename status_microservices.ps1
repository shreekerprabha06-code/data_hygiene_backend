$ErrorActionPreference = "SilentlyContinue"

$BackendDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$LogDir = Join-Path $BackendDir "logs"
$Ports = 8000, 8001, 8002, 8003, 8004, 8005

Write-Host "Port status:"
foreach ($Port in $Ports) {
    $Line = netstat -ano | Select-String "LISTENING\s+\d+$" | Where-Object {
        $_.Line -match "[:.]$Port\s+"
    } | Select-Object -First 1

    if ($Line -and $Line.Line -match "\s+(\d+)$") {
        Write-Host "  $Port listening (PID $($Matches[1]))" -ForegroundColor Green
    } else {
        Write-Host "  $Port not listening" -ForegroundColor Red
    }
}

Write-Host ""
Write-Host "Gateway check:"
try {
    $Response = Invoke-WebRequest -Uri "http://localhost:8000/health" -UseBasicParsing -TimeoutSec 5
    Write-Host "  http://localhost:8000/health -> $($Response.StatusCode) $($Response.Content)" -ForegroundColor Green
} catch {
    Write-Host "  http://localhost:8000/health failed: $($_.Exception.Message)" -ForegroundColor Red
}

Write-Host ""
Write-Host "Recent errors:"
if (Test-Path $LogDir) {
    Get-ChildItem $LogDir -Filter "*.err.log" | ForEach-Object {
        Write-Host "---- $($_.Name) ----"
        $Content = Get-Content $_.FullName -Tail 20
        if ($Content) {
            $Content
        } else {
            Write-Host "(empty)"
        }
    }
} else {
    Write-Host "No logs directory found."
}
