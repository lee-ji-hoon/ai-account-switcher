#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_SOURCE="$("$SCRIPT_DIR/run.sh" --build-only)"
TARGET_DIR="$HOME/Applications"
TARGET_APP="$TARGET_DIR/Switchboard.app"
BACKUP_APP=""

restore_previous_app() {
    install_rc=$?
    if [[ -e "$TARGET_APP" ]]; then
        command rm -rf "$TARGET_APP"
    fi
    if [[ -n "$BACKUP_APP" && -d "$BACKUP_APP" ]]; then
        mv "$BACKUP_APP" "$TARGET_APP"
        echo "설치 실패 · 기존 앱 복구 완료: $TARGET_APP" >&2
    else
        echo "설치 실패 · 불완전한 앱 제거 완료: $TARGET_APP" >&2
    fi
    exit "$install_rc"
}

mkdir -p "$TARGET_DIR"
if [[ -e "$TARGET_APP" && ! -d "$TARGET_APP" ]]; then
    echo "설치 대상이 앱 번들이 아닙니다: $TARGET_APP" >&2
    exit 1
fi
if [[ -d "$TARGET_APP" ]]; then
    BACKUP_APP="$TARGET_DIR/Switchboard.backup-$(date +%Y%m%d-%H%M%S)-$$.app"
    mv "$TARGET_APP" "$BACKUP_APP"
    echo "기존 앱 백업: $BACKUP_APP"
fi

trap restore_previous_app ERR
ditto "$APP_SOURCE" "$TARGET_APP"
codesign --verify --deep --strict "$TARGET_APP"
trap - ERR
echo "설치 완료: $TARGET_APP"
