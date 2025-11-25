# Setup Supabase Experience Tables

Write-Host "=== Supabase Experience Database Setup ===" -ForegroundColor Cyan
Write-Host ""

# Check if backend config exists
$configPath = "backend\database\config.py"
if (-not (Test-Path $configPath)) {
    Write-Host "[X] Backend config not found at: $configPath" -ForegroundColor Red
    Write-Host "Please ensure Supabase is configured first." -ForegroundColor Yellow
    exit 1
}

Write-Host "[*] Testing Supabase connection..." -ForegroundColor Yellow
try {
    $result = python -c "from backend.database.config import SUPABASE_URL, SUPABASE_SERVICE_KEY; from supabase import create_client; client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY); print('OK')" 2>&1
    
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[X] Supabase connection failed" -ForegroundColor Red
        Write-Host $result -ForegroundColor Gray
        exit 1
    }
    
    Write-Host "[OK] Supabase connection successful" -ForegroundColor Green
} catch {
    Write-Host "[X] Error testing connection: $_" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "=== Experience Schema Setup ===" -ForegroundColor Cyan
Write-Host ""
Write-Host "The experience database requires 7 tables to be created in Supabase:" -ForegroundColor White
Write-Host "  1. entity_knowledge       - Validated entities with confidence" -ForegroundColor Gray
Write-Host "  2. pattern_performance    - Regex pattern success rates" -ForegroundColor Gray
Write-Host "  3. section_templates      - Paper structure templates" -ForegroundColor Gray
Write-Host "  4. result_baselines       - Expected metric ranges" -ForegroundColor Gray
Write-Host "  5. agent_execution_log    - Agent performance tracking" -ForegroundColor Gray
Write-Host "  6. agent_consensus_history - Conflict resolution log" -ForegroundColor Gray
Write-Host "  7. entity_relationships   - Cross-paper entity graph" -ForegroundColor Gray
Write-Host ""

$schemaFile = "backend\database\experience_schema.sql"
if (-not (Test-Path $schemaFile)) {
    Write-Host "[X] Schema file not found: $schemaFile" -ForegroundColor Red
    exit 1
}

Write-Host "[i] Schema file found: $schemaFile" -ForegroundColor Cyan
Write-Host ""
Write-Host "INSTRUCTIONS:" -ForegroundColor Yellow
Write-Host ""
Write-Host "1. Open Supabase Dashboard: https://app.supabase.com" -ForegroundColor White
Write-Host "2. Select your project" -ForegroundColor White
Write-Host "3. Go to: SQL Editor (left sidebar)" -ForegroundColor White
Write-Host "4. Click 'New Query'" -ForegroundColor White
Write-Host "5. Copy the contents of this file:" -ForegroundColor White
Write-Host "   $schemaFile" -ForegroundColor Cyan
Write-Host "6. Paste into the SQL editor" -ForegroundColor White
Write-Host "7. Click 'Run' to execute" -ForegroundColor White
Write-Host ""
Write-Host "[*] Opening schema file for you to copy..." -ForegroundColor Yellow
Write-Host ""

# Open the file in default editor
Start-Process notepad.exe -ArgumentList $schemaFile

Write-Host ""
$openBrowser = Read-Host "Open Supabase SQL Editor in browser? (y/n)"
if ($openBrowser -eq "y") {
    Write-Host "[*] Opening Supabase..." -ForegroundColor Yellow
    
    # Try to get project URL from config
    try {
        $url = python -c "from backend.database.config import SUPABASE_URL; print(SUPABASE_URL)" 2>&1
        if ($url -match "https://([a-z0-9]+)\.supabase\.co") {
            $projectId = $matches[1]
            $sqlEditorUrl = "https://app.supabase.com/project/$projectId/sql/new"
            Start-Process $sqlEditorUrl
        } else {
            Start-Process "https://app.supabase.com"
        }
    } catch {
        Start-Process "https://app.supabase.com"
    }
}

Write-Host ""
Write-Host "After running the SQL script in Supabase:" -ForegroundColor Yellow
Write-Host "1. Verify tables were created (check 'Table Editor')" -ForegroundColor White
Write-Host "2. Run agent mode to test:" -ForegroundColor White
Write-Host "   python main.py --agent-mode --max-results 1 --config config.yaml" -ForegroundColor Gray
Write-Host ""
Write-Host "The agent system will now be able to:" -ForegroundColor Cyan
Write-Host "  - Learn entity names across papers" -ForegroundColor White
Write-Host "  - Detect outlier results" -ForegroundColor White
Write-Host "  - Track pattern performance" -ForegroundColor White
Write-Host "  - Build cross-paper knowledge graph" -ForegroundColor White
Write-Host ""
