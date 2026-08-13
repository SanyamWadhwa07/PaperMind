# Research Paper Summarizer - Setup Script

Write-Host "=" -NoNewline -ForegroundColor Cyan
Write-Host "="*60 -ForegroundColor Cyan
Write-Host "Research Paper Summarizer - Full Stack Setup" -ForegroundColor Green
Write-Host "=" -NoNewline -ForegroundColor Cyan
Write-Host "="*60 -ForegroundColor Cyan
Write-Host ""

# Check Python
Write-Host "[1/4] Checking Python..." -ForegroundColor Yellow
if (Get-Command python -ErrorAction SilentlyContinue) {
    $pythonVersion = python --version
    Write-Host "  ✓ $pythonVersion found" -ForegroundColor Green
} else {
    Write-Host "  ✗ Python not found! Please install Python 3.8+" -ForegroundColor Red
    exit 1
}

# Check Node.js
Write-Host "[2/4] Checking Node.js..." -ForegroundColor Yellow
if (Get-Command node -ErrorAction SilentlyContinue) {
    $nodeVersion = node --version
    Write-Host "  ✓ Node.js $nodeVersion found" -ForegroundColor Green
} else {
    Write-Host "  ✗ Node.js not found! Please install Node.js 18+" -ForegroundColor Red
    exit 1
}

# Setup Backend
Write-Host "[3/4] Setting up Backend..." -ForegroundColor Yellow
Write-Host "  Installing backend dependencies..." -ForegroundColor Cyan
Set-Location backend
pip install -r requirements.txt --quiet
if ($LASTEXITCODE -eq 0) {
    Write-Host "  ✓ Backend dependencies installed" -ForegroundColor Green
} else {
    Write-Host "  ✗ Failed to install backend dependencies" -ForegroundColor Red
}
Set-Location ..

# Setup Frontend
Write-Host "[4/4] Setting up Frontend..." -ForegroundColor Yellow
Write-Host "  Installing Node dependencies (this may take a few minutes)..." -ForegroundColor Cyan
Set-Location frontend
npm install --silent
if ($LASTEXITCODE -eq 0) {
    Write-Host "  ✓ Frontend dependencies installed" -ForegroundColor Green
} else {
    Write-Host "  ✗ Failed to install frontend dependencies" -ForegroundColor Red
}
Set-Location ..

Write-Host ""
Write-Host "=" -NoNewline -ForegroundColor Cyan
Write-Host "="*60 -ForegroundColor Cyan
Write-Host "Setup Complete!" -ForegroundColor Green
Write-Host "=" -NoNewline -ForegroundColor Cyan
Write-Host "="*60 -ForegroundColor Cyan
Write-Host ""
Write-Host "Next Steps:" -ForegroundColor Yellow
Write-Host ""
Write-Host "1. Copy backend/.env.example to backend/.env and fill in Supabase + LLM keys" -ForegroundColor Cyan
Write-Host ""
Write-Host "2. Start Backend (Terminal 1):" -ForegroundColor Cyan
Write-Host "   cd backend" -ForegroundColor White
Write-Host "   python -m uvicorn main_app:app --reload --port 8000" -ForegroundColor White
Write-Host ""
Write-Host "3. Start Frontend (Terminal 2):" -ForegroundColor Cyan
Write-Host "   cd frontend" -ForegroundColor White
Write-Host "   npm run dev" -ForegroundColor White
Write-Host ""
Write-Host "4. Open Browser:" -ForegroundColor Cyan
Write-Host "   http://localhost:3000" -ForegroundColor White
Write-Host ""
Write-Host "For detailed documentation, see README.md and CLAUDE.md." -ForegroundColor Yellow
Write-Host ""
