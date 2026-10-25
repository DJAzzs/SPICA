#!/usr/bin/env bash
set -e
VERSION="${1:-0.1.0}"
echo "Building SPICA macOS .app..."
pyinstaller spica.spec --noconfirm --clean --windowed
if command -v hdiutil >/dev/null; then
    hdiutil create -volname "SPICA" -srcfolder dist/SPICA -ov -format UDZO "SPICA-${VERSION}.dmg"
    echo "✓ SPICA-${VERSION}.dmg"
else
    echo "✓ dist/SPICA/ (folder .app)"
fi
