# Start all Micro Frontends
# Run this in the root directory: c:\Users\user\Desktop\data-hygiene

Write-Host "Starting Data Hygiene MFEs..." -ForegroundColor Cyan

$refreshPath = '$env:Path = [System.Environment]::GetEnvironmentVariable(\"Path\",\"Machine\") + \";\" + [System.Environment]::GetEnvironmentVariable(\"Path\",\"User\");'
Start-Process powershell -ArgumentList "-NoExit", "-Command", "$refreshPath cd mfe-dashboard; npm run dev"
Start-Process powershell -ArgumentList "-NoExit", "-Command", "$refreshPath cd mfe-details; npm run dev"
Start-Process powershell -ArgumentList "-NoExit", "-Command", "$refreshPath cd mfe-auth; npm install; npm run dev"
Start-Process powershell -ArgumentList "-NoExit", "-Command", "$refreshPath cd mfe-shell; npm run dev"

Write-Host "Apps are launching!" -ForegroundColor Green
Write-Host "Dashboard: http://localhost:5001"
Write-Host "Details:   http://localhost:5002"
Write-Host "Auth:      http://localhost:5004"
Write-Host "Host:      http://localhost:5003 (Main Entry)"
