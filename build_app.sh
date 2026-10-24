#!/bin/bash
# Gera "Grupos TS3.app" (janela própria, sem navegador)
set -e
cd "$(dirname "$0")"
APP="Grupos TS3.app"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
swiftc -O app/main.swift -o "$APP/Contents/MacOS/GruposTS3"
cp server.py updater.py version.txt index.html skin-frost.jpg icon.png AppIcon.icns "$APP/Contents/Resources/"
cat > "$APP/Contents/Info.plist" <<P
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>CFBundleIconFile</key><string>AppIcon</string>
<key>CFBundleName</key><string>Grupos TS3</string>
<key>CFBundleExecutable</key><string>GruposTS3</string>
<key>CFBundleIdentifier</key><string>local.gruposts3</string>
<key>CFBundlePackageType</key><string>APPL</string>
<key>CFBundleVersion</key><string>1</string>
<key>LSMinimumSystemVersion</key><string>11.0</string>
<key>NSAppTransportSecurity</key><dict><key>NSAllowsLocalNetworking</key><true/></dict>
</dict></plist>
P
codesign --force --sign - "$APP" >/dev/null 2>&1 || true
# leva a API key e presets já configurados
D="$HOME/Library/Application Support/GruposTS3"; mkdir -p "$D"
[ -f config.json ] && [ ! -f "$D/config.json" ] && cp config.json "$D/" || true
[ -f presets.json ] && [ ! -f "$D/presets.json" ] && cp presets.json "$D/" || true
echo "Pronto: $APP"
