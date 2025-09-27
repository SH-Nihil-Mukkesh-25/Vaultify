Write-Host "🚀 Setting up Vaultify Security Dashboard..." -ForegroundColor Green
Write-Host ""
Write-Host "Please enter your Gemini API key:" -ForegroundColor Yellow
$apiKey = Read-Host "API Key"
Write-Host ""
Write-Host "Starting backend with API key..." -ForegroundColor Green
$env:GEMINI_API_KEY = $apiKey
python backend.py
