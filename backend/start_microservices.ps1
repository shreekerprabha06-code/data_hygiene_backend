param(
    [switch]$Reload
)

$ErrorActionPreference = "Stop"

$BackendDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $BackendDir
$LogDir = Join-Path $BackendDir "logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

if (Test-Path ".\.venv\Scripts\python.exe") {
    $Python = Join-Path $BackendDir ".venv\Scripts\python.exe"
} elseif (Test-Path ".\venv\Scripts\python.exe") {
    $Python = Join-Path $BackendDir "venv\Scripts\python.exe"
} else {
    $Python = "python"
}

$Services = @(
    @{ Name = "masterlist-service"; Port = 8001; Module = "app.services.masterlist_service.main:app" },
    @{ Name = "pipeline-service"; Port = 8002; Module = "app.services.pipeline_service.main:app" },
    @{ Name = "standardization-service"; Port = 8003; Module = "app.services.standardization_service.main:app" },
    @{ Name = "ingestion-service"; Port = 8004; Module = "app.services.ingestion_service.main:app" },
    @{ Name = "trigger-service"; Port = 8005; Module = "app.services.trigger_service.main:app" }
)

Write-Host "Backend directory: $BackendDir"
Write-Host "Logs directory: $LogDir"

Write-Host "Starting NGINX API Gateway on port 8000..."
$NginxConf = Join-Path $BackendDir "nginx.conf"
Start-Process -FilePath "C:\nginx\nginx.exe" -ArgumentList "-c `"$NginxConf`"" -WorkingDirectory "C:\nginx" -WindowStyle Hidden

foreach ($Service in $Services) {
    Write-Host "Starting $($Service.Name) on port $($Service.Port)..."
    $Args = @("-m", "uvicorn", $Service.Module, "--host", "0.0.0.0", "--port", "$($Service.Port)")
    if ($Reload) {
        $Args += "--reload"
    }

    $OutFile = Join-Path $LogDir "$($Service.Name).out.log"
    $ErrFile = Join-Path $LogDir "$($Service.Name).err.log"
    Remove-Item -LiteralPath $OutFile, $ErrFile -ErrorAction SilentlyContinue

    Start-Process `
        -FilePath $Python `
        -ArgumentList $Args `
        -WorkingDirectory $BackendDir `
        -RedirectStandardOutput $OutFile `
        -RedirectStandardError $ErrFile `
        -WindowStyle Hidden
}

Write-Host "All microservices launched."
Write-Host "Run .\status_microservices.ps1 to check ports and view failures."
