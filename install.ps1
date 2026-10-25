# SPICA Installer (Windows)
Write-Host "╔══════════════════════════════════════════╗" -ForegroundColor Cyan
Write-Host "║       SPICA Installer (Windows)          ║" -ForegroundColor Cyan
Write-Host "╚══════════════════════════════════════════╝" -ForegroundColor Cyan

# Check prerequisites
Write-Host "▸ Checking prerequisites..." -ForegroundColor Yellow
$pythonOK = Get-Command python -ErrorAction SilentlyContinue
$nodeOK = Get-Command node -ErrorAction SilentlyContinue

if (-not $pythonOK) {
    Write-Host "✗ Python 3.12+ required. Install from python.org" -ForegroundColor Red
    exit 1
}
if (-not $nodeOK) {
    Write-Host "✗ Node.js 18+ required. Install from nodejs.org" -ForegroundColor Red
    exit 1
}
Write-Host "  ✓ Python $(python --version)"
Write-Host "  ✓ Node $(node --version)"

# Install
Write-Host "▸ Installing Python dependencies..." -ForegroundColor Yellow
python -m venv .venv
if (Test-Path pip.conf) { Copy-Item pip.conf .venv/pip.conf }
.venv\Scripts\pip install -r requirements.txt --quiet
Write-Host "  ✓ Python deps installed"

Write-Host "▸ Bundling DSH runtime..." -ForegroundColor Yellow
if (-not (Test-Path "runtime\dsh\node_modules\@deepseek-ai\dsh")) {
    New-Item -ItemType Directory -Force -Path "runtime\dsh" | Out-Null
    Push-Location "runtime\dsh"
    npm init -y 2>$null
    npm install "@deepseek-ai/dsh" --registry="https://registry.npmmirror.com" --cache "../../.cache/npm" --no-audit --no-fund
    Pop-Location
}
Write-Host "  ✓ DSH runtime ready"

Write-Host "▸ Downloading speech models..." -ForegroundColor Yellow
.venv\Scripts\python -m tools.download_models
Write-Host "  ✓ Models downloaded"

Write-Host "▸ Building web frontend..." -ForegroundColor Yellow
Push-Location web
npm install --registry="https://registry.npmmirror.com" --cache "../.cache/npm" --no-audit --no-fund
npm run build-only
Pop-Location
Write-Host "  ✓ Frontend built"

Write-Host ""
Write-Host "╔══════════════════════════════════════════╗" -ForegroundColor Green
Write-Host "║           Installation Complete!          ║" -ForegroundColor Green
Write-Host "╠══════════════════════════════════════════╣" -ForegroundColor Green
Write-Host "║  Start:  .venv\Scripts\python -m server.main ║" -ForegroundColor Green
Write-Host "║  Open:   http://127.0.0.1:8666            ║" -ForegroundColor Green
Write-Host "╚══════════════════════════════════════════╝" -ForegroundColor Green
