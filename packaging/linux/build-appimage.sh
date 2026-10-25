#!/usr/bin/env bash
set -e
VERSION="${1:-0.1.0}"

echo "Building SPICA AppImage v${VERSION}..."

# 1. PyInstaller 打包
pyinstaller spica.spec --noconfirm --clean

# 2. 组装 AppDir
APPDIR=build/SPICA.AppDir
rm -rf "$APPDIR"
mkdir -p "$APPDIR/usr/bin" "$APPDIR/usr/share" "$APPDIR/usr/share/applications" "$APPDIR/usr/share/icons/hicolor/512x512/apps"

# PyInstaller 输出
cp -r dist/SPICA/* "$APPDIR/usr/bin/"

# Desktop entry
cat > "$APPDIR/usr/share/applications/spica.desktop" << DESKTOP
[Desktop Entry]
Type=Application
Name=SPICA
Comment=Voice-first local AI Agent console
Exec=spica
Icon=spica
Categories=Development;Utility;
Terminal=true
DESKTOP

# Icon (用 favicon SVG 转 PNG 或直接用 SVG)
cp web/public/favicon.svg "$APPDIR/usr/share/icons/hicolor/512x512/apps/spica.svg"

# AppRun
cat > "$APPDIR/AppRun" << 'APPRUN'
#!/usr/bin/env bash
SELF=$(readlink -f "$0")
HERE=${SELF%/*}
exec "${HERE}/usr/bin/SPICA" "$@"
APPRUN
chmod +x "$APPDIR/AppRun"

# 3. 打包 AppImage
echo "Fetching appimagetool..."
wget -q -O /tmp/appimagetool "https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage"
chmod +x /tmp/appimagetool

ARCH=x86_64 /tmp/appimagetool "$APPDIR" "SPICA-${VERSION}-x86_64.AppImage"
echo "✓ SPICA-${VERSION}-x86_64.AppImage"
