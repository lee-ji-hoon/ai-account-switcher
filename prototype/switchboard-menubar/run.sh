#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BUILD_DIR="$SCRIPT_DIR/.build"
APP_DIR="$BUILD_DIR/Switchboard.app"
PLUGIN_MANIFEST="$SCRIPT_DIR/../../.claude-plugin/plugin.json"
BUILD_ONLY=false
APP_ARGS=()

for arg in "$@"; do
    if [[ "$arg" == "--build-only" ]]; then
        BUILD_ONLY=true
    else
        APP_ARGS+=("$arg")
    fi
done

cd "$SCRIPT_DIR"
# Keep stdout machine-readable: callers capture the final app path from it.
# Build diagnostics remain visible to interactive users and CI via stderr.
swift build >&2

command rm -rf "$APP_DIR"
mkdir -p "$APP_DIR/Contents/MacOS" "$APP_DIR/Contents/Resources"
cp "$SCRIPT_DIR/Info.plist" "$APP_DIR/Contents/Info.plist"
PLUGIN_VERSION="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["version"])' "$PLUGIN_MANIFEST")"
/usr/libexec/PlistBuddy -c "Set :CFBundleShortVersionString $PLUGIN_VERSION" "$APP_DIR/Contents/Info.plist"
/usr/libexec/PlistBuddy -c "Set :CFBundleVersion $PLUGIN_VERSION" "$APP_DIR/Contents/Info.plist"
cp "$BUILD_DIR/debug/switchboard-prototype" "$APP_DIR/Contents/MacOS/switchboard-prototype"
cp "$SCRIPT_DIR/Resources/SwitchboardIcon.icns" "$APP_DIR/Contents/Resources/SwitchboardIcon.icns"
cp "$SCRIPT_DIR/Resources/SwitchboardIcon-1024.png" "$APP_DIR/Contents/Resources/SwitchboardIcon-1024.png"
for provider_icon in claude.jpg codex.png grok.jpg gemini.jpg; do
    source_icon="$SCRIPT_DIR/Resources/provider-icons/$provider_icon"
    [[ -f "$source_icon" ]] || {
        echo "Required provider icon source is missing: $provider_icon" >&2
        exit 1
    }
    cp "$source_icon" "$APP_DIR/Contents/Resources/ProviderIcon-$provider_icon"
done
cp "$SCRIPT_DIR/Resources/live_snapshot.py" "$APP_DIR/Contents/Resources/live_snapshot.py"
cp "$SCRIPT_DIR/../../account_manager.py" "$APP_DIR/Contents/Resources/account_manager.py"
command rm -rf "$APP_DIR/Contents/Resources/claude_account_manager"
cp -R "$SCRIPT_DIR/../../claude_account_manager" "$APP_DIR/Contents/Resources/claude_account_manager"

codesign --force --deep --sign - "$APP_DIR" >/dev/null

if [[ "$BUILD_ONLY" == true ]]; then
    printf '%s\n' "$APP_DIR"
    exit 0
fi

open "$APP_DIR" --args "${APP_ARGS[@]}"
