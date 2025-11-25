# Ollama Setup for Agent System

Write-Host "=== Ollama Setup for Research Paper Summarizer ===" -ForegroundColor Cyan
Write-Host ""

# Check if Ollama is installed
$ollamaInstalled = Get-Command ollama -ErrorAction SilentlyContinue

if (-not $ollamaInstalled) {
    Write-Host "[X] Ollama not found!" -ForegroundColor Red
    Write-Host ""
    Write-Host "[!] Please download and install Ollama from:" -ForegroundColor Yellow
    Write-Host "    https://ollama.com/download" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "After installation:" -ForegroundColor Yellow
    Write-Host "1. Restart this PowerShell terminal" -ForegroundColor White
    Write-Host "2. Run this script again: .\setup_ollama.ps1" -ForegroundColor White
    Write-Host ""
    
    # Try to open download page
    $openBrowser = Read-Host "Open download page in browser? (y/n)"
    if ($openBrowser -eq "y") {
        Start-Process "https://ollama.com/download"
    }
    
    exit 1
}

Write-Host "[OK] Ollama is installed!" -ForegroundColor Green
Write-Host ""

# Check if Ollama service is running
Write-Host "[*] Checking Ollama service..." -ForegroundColor Yellow
try {
    $response = Invoke-WebRequest -Uri "http://localhost:11434/api/tags" -Method GET -TimeoutSec 5 -ErrorAction Stop
    Write-Host "[OK] Ollama service is running!" -ForegroundColor Green
} catch {
    Write-Host "[!] Ollama service not running" -ForegroundColor Yellow
    Write-Host "[*] Starting Ollama service..." -ForegroundColor Yellow
    
    # Start Ollama in background
    Start-Process -FilePath "ollama" -ArgumentList "serve" -WindowStyle Hidden
    
    Write-Host "[*] Waiting for service to start (5 seconds)..." -ForegroundColor Yellow
    Start-Sleep -Seconds 5
    
    try {
        $response = Invoke-WebRequest -Uri "http://localhost:11434/api/tags" -Method GET -TimeoutSec 5 -ErrorAction Stop
        Write-Host "[OK] Ollama service started!" -ForegroundColor Green
    } catch {
        Write-Host "[X] Failed to start Ollama service" -ForegroundColor Red
        Write-Host "Try running manually: ollama serve" -ForegroundColor Yellow
        exit 1
    }
}

Write-Host ""

# List currently installed models
Write-Host "[*] Checking installed models..." -ForegroundColor Yellow
$installedModels = ollama list 2>&1

if ($installedModels -match "qwen2.5:3b") {
    Write-Host "[OK] qwen2.5:3b already installed" -ForegroundColor Green
} else {
    Write-Host "[!] qwen2.5:3b not found" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "[*] Downloading qwen2.5:3b (2.3GB)..." -ForegroundColor Cyan
    Write-Host "    This may take several minutes depending on your internet speed..." -ForegroundColor Gray
    Write-Host ""
    
    ollama pull qwen2.5:3b
    
    if ($LASTEXITCODE -eq 0) {
        Write-Host "[OK] qwen2.5:3b downloaded successfully!" -ForegroundColor Green
    } else {
        Write-Host "[X] Failed to download qwen2.5:3b" -ForegroundColor Red
        Write-Host "Try running manually: ollama pull qwen2.5:3b" -ForegroundColor Yellow
        exit 1
    }
}

Write-Host ""

# Check alternative models
if ($installedModels -match "phi3:mini") {
    Write-Host "[OK] phi3:mini also available (2.2GB alternative)" -ForegroundColor Green
} else {
    Write-Host "[i] Optional: You can also install phi3:mini as alternative:" -ForegroundColor Cyan
    Write-Host "    ollama pull phi3:mini" -ForegroundColor Gray
}

Write-Host ""
Write-Host "=== Testing Ollama ===" -ForegroundColor Cyan

# Test generation
Write-Host "[*] Testing text generation..." -ForegroundColor Yellow
$testPrompt = "Say 'Hello, I am ready!' in one sentence."

try {
    $testResponse = ollama run qwen2.5:3b $testPrompt 2>&1
    Write-Host "[OK] Generation test passed!" -ForegroundColor Green
    Write-Host "Response: $testResponse" -ForegroundColor Gray
} catch {
    Write-Host "[!] Generation test failed, but model is installed" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "=== Setup Complete! ===" -ForegroundColor Green
Write-Host ""
Write-Host "[OK] Ollama is ready for agent mode" -ForegroundColor Green
Write-Host ""
Write-Host "Next steps:" -ForegroundColor Cyan
Write-Host "1. Make sure Ollama service stays running (it starts automatically)" -ForegroundColor White
Write-Host "2. Run agent mode:" -ForegroundColor White
Write-Host "   python main.py --agent-mode --max-results 1 --config config.yaml" -ForegroundColor Gray
Write-Host ""
Write-Host "Model Information:" -ForegroundColor Cyan
Write-Host "  - qwen2.5:3b: 2.3GB, fast, good quality" -ForegroundColor White
Write-Host "  - phi3:mini: 2.2GB, alternative option" -ForegroundColor White
Write-Host ""
Write-Host "Useful commands:" -ForegroundColor Cyan
Write-Host "  ollama list           # List installed models" -ForegroundColor Gray
Write-Host "  ollama pull <model>   # Download a model" -ForegroundColor Gray
Write-Host "  ollama rm <model>     # Remove a model" -ForegroundColor Gray
Write-Host "  ollama serve          # Start Ollama service manually" -ForegroundColor Gray
Write-Host ""
