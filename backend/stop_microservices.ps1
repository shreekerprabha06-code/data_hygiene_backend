$Ports = 8000, 8001, 8002, 8003, 8004, 8005
$Pids = @()
foreach ($Port in $Ports) {
    $Lines = netstat -ano | Select-String "LISTENING\s+\d+$" | Where-Object {
        $_.Line -match "[:.]$Port\s+"
    }
    foreach ($Line in $Lines) {
        if ($Line.Line -match "\s+(\d+)$") {
            $Pids += [int]$Matches[1]
        }
    }
}

$Pids = $Pids | Sort-Object -Unique

Write-Host "Stopping NGINX"
Stop-Process -Name "nginx" -Force -ErrorAction SilentlyContinue

foreach ($ProcId in $Pids) {
    if ($ProcId -and $ProcId -ne 0) {
        Write-Host "Stopping PID $ProcId"
        Stop-Process -Id $ProcId -Force -ErrorAction SilentlyContinue
    }
}
