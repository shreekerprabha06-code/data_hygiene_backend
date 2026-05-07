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

foreach ($Pid in $Pids) {
    if ($Pid -and $Pid -ne 0) {
        Write-Host "Stopping PID $Pid"
        Stop-Process -Id $Pid -Force -ErrorAction SilentlyContinue
    }
}
