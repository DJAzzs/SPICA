#!/usr/bin/env bash
set -e
echo "╔══════════════════════════════════════════╗"
echo "║       SPICA Installer (Linux/macOS)      ║"
echo "╚══════════════════════════════════════════╝"

# Check prerequisites
echo "▸ Checking prerequisites..."
command -v python3.12 >/dev/null 2>&1 || command -v python3 >/dev/null 2>&1 || {
    echo "✗ Python 3.12+ required. Install from python.org"
    exit 1
}
command -v node >/dev/null 2>&1 || {
    echo "✗ Node.js 18+ required. Install from nodejs.org"
    exit 1
}
command -v npm >/dev/null 2>&1 || {
    echo "✗ npm required (comes with Node.js)"
    exit 1
}
echo "  ✓ Python $(python3 --version 2>&1)"
echo "  ✓ Node $(node --version)"

# Install
echo "▸ Installing Python dependencies..."
python3 -m venv .venv 2>/dev/null || python3.12 -m venv .venv
cp pip.conf .venv/pip.conf 2>/dev/null || true
.venv/bin/pip install -r requirements.txt --quiet
echo "  ✓ Python deps installed"

echo "▸ Bundling DSH runtime (~883MB)..."
if [ ! -d runtime/dsh/node_modules/@deepseek-ai/dsh ]; then
    mkdir -p runtime/dsh
    cd runtime/dsh
    npm init -y > /dev/null 2>&1
    npm install @deepseek-ai/dsh \
        --registry=https://registry.npmmirror.com \
        --cache ../../.cache/npm --no-audit --no-fund
    cd ../..
fi
echo "  ✓ DSH runtime ready"

echo "▸ Downloading speech models (~480MB)..."
.venv/bin/python -m tools.download_models
echo "  ✓ Models downloaded"

echo "▸ Building web frontend..."
cd web
npm install --registry=https://registry.npmmirror.com --cache ../.cache/npm --no-audit --no-fund
npm run build-only
cd ..
echo "  ✓ Frontend built"

echo ""
echo "╔══════════════════════════════════════════╗"
echo "║           Installation Complete!          ║"
echo "╠══════════════════════════════════════════╣"
echo "║  Start:  make up                          ║"
echo "║  Open:   http://127.0.0.1:8666            ║"
echo "║  Check:  make check                       ║"
echo "╚══════════════════════════════════════════╝"
