#!/usr/bin/env python3
"""Emit an allowlisted Switchboard snapshot. Never emits credential material."""

from __future__ import annotations

import json
import os
import pty
import re
import select
import shutil
import struct
import subprocess
import sys
import termios
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.dont_write_bytecode = True
RESOURCE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(RESOURCE_DIR))
SOURCE_ROOT = RESOURCE_DIR.parents[2] if len(RESOURCE_DIR.parents) > 2 else None
if SOURCE_ROOT and (SOURCE_ROOT / "claude_account_manager").is_dir():
    sys.path.insert(0, str(SOURCE_ROOT))


def _remaining(target) -> str:
    if not target:
        return "시각 미제공"
    if isinstance(target, (int, float)):
        target = datetime.fromtimestamp(target, tz=timezone.utc)
    if target.tzinfo is None:
        target = target.replace(tzinfo=timezone.utc)
    seconds = max(0, int((target - datetime.now(timezone.utc)).total_seconds()))
    days, remainder = divmod(seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes = remainder // 60
    if days:
        return f"{days}일 {hours}시간"
    if hours:
        return f"{hours}시간 {minutes}분"
    return f"{minutes}분"


def _window(label: str, used, reset_at=None, reset_after=None) -> dict:
    try:
        percent = max(0, min(100, int(round(float(used)))))
    except (TypeError, ValueError):
        percent = 0
    if reset_after is not None:
        try:
            reset_at = datetime.now(timezone.utc).timestamp() + int(reset_after)
        except (TypeError, ValueError):
            reset_at = None
    return {"label": label, "usedPercent": percent, "resetsIn": _remaining(reset_at)}


def _parse_iso_datetime(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def _health(raw: str) -> str:
    return {
        "valid": "ready",
        "ok": "ready",
        "expiring": "expiring",
    }.get(raw, "unavailable")


def _safe_claude_usage(fetch, is_current, credential, credential_path):
    """Fail closed when a stored account credential cannot be loaded."""
    if not is_current and credential is None:
        return None, None
    return fetch(
        None if is_current else credential,
        include_token_status=True,
        credential_file=None if is_current else credential_path,
        _allow_cache=False,
    )


def _private_account_file(root, filename):
    """Resolve one regular file directly below an account store."""
    if not isinstance(filename, str) or not filename:
        return None
    try:
        resolved_root = root.resolve()
        path = root / filename
        resolved = path.resolve()
    except (OSError, RuntimeError):
        return None
    if resolved.parent != resolved_root or path.is_symlink() or not resolved.is_file():
        return None
    return resolved


def claude_provider() -> dict:
    from claude_account_manager.account import is_same_account
    from claude_account_manager.api import _fetch_usage_from_api
    from claude_account_manager.config import ACCOUNTS_DIR
    from claude_account_manager.keychain import get_keychain_credential
    from claude_account_manager.owner import credential_matches_slot
    from claude_account_manager.storage import get_current_account, load_index

    index = load_index()
    current = get_current_account()
    accounts = []
    active_id = ""
    for stored in index.get("accounts", []):
        is_current = is_same_account(stored, current)
        credential = get_keychain_credential() if is_current else None
        credential_path = None
        if not is_current:
            credential_path = _private_account_file(ACCOUNTS_DIR, stored.get("credentialFile"))
            try:
                credential = json.loads(credential_path.read_text()) if credential_path else None
            except Exception:
                credential = None
        try:
            owner_matches = credential_matches_slot(credential, stored) if credential else None
        except Exception:
            owner_matches = None
        try:
            if owner_matches is not True:
                raise ValueError("credential owner unavailable or mismatched")
            usage, token_status = _safe_claude_usage(
                _fetch_usage_from_api,
                is_current,
                credential,
                credential_path,
            )
        except Exception:
            usage, token_status = None, None
        windows = []
        if usage:
            if usage.get("fiveHour") is not None:
                windows.append(_window("5시간", usage["fiveHour"], usage.get("fiveHourResetAt")))
            if usage.get("sevenDay") is not None:
                windows.append(_window("주간", usage["sevenDay"], usage.get("sevenDayResetAt")))
        raw_status = getattr(token_status, "value", str(token_status or ""))
        health = _health(raw_status)
        accounts.append({
            "id": f"claude-{stored['id']}",
            "name": stored.get("name") or stored["id"],
            "email": stored.get("email", ""),
            "plan": (usage or {}).get("planName") or stored.get("plan", "?"),
            "health": health,
            "switchable": health == "ready",
            "usage": windows,
            "benefits": [],
            "origin": "live",
        })
        if is_current and owner_matches is True:
            active_id = f"claude-{stored['id']}"
    return _provider("claude", active_id, accounts, "Keychain + Anthropic usage · credential 소유권 검증")


def _codex_label(window: dict) -> str:
    try:
        seconds = int(window.get("limit_window_seconds", 0))
    except (TypeError, ValueError):
        return "한도"
    for expected, label in ((18000, "5시간"), (86400, "일간"), (604800, "주간"), (2592000, "월간")):
        if abs(seconds - expected) <= expected * 0.05:
            return label
    return "한도"


def codex_provider() -> dict:
    from claude_account_manager.codex_provider import (
        CODEX_ACCOUNTS_DIR,
        fetch_codex_usage,
        get_codex_auth_info,
        get_codex_token_status,
        get_current_codex_account_id,
        load_codex_index,
        read_codex_auth,
    )

    index = load_codex_index()
    current_account_id = get_current_codex_account_id()
    accounts = []
    active_id = ""
    for stored in index.get("accounts", []):
        current = stored.get("account_id") == current_account_id
        stored_id = stored.get("id")
        auth_path = None
        if isinstance(stored_id, str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", stored_id):
            auth_path = _private_account_file(CODEX_ACCOUNTS_DIR, f"auth_{stored_id}.json")
        auth = read_codex_auth() if current else (read_codex_auth(auth_path) if auth_path else None)
        expected_account_id = stored.get("account_id")
        auth_matches = bool(
            auth
            and expected_account_id
            and auth.get("tokens", {}).get("account_id") == expected_account_id
        )
        if not auth_matches:
            auth = None
        info = get_codex_auth_info(auth or {})
        usage = fetch_codex_usage(auth) if auth else None
        windows = []
        if usage:
            rate_limit = usage.get("rate_limit") or {}
            for key in ("primary_window", "secondary_window"):
                item = rate_limit.get(key)
                if item:
                    windows.append(_window(
                        _codex_label(item),
                        item.get("used_percent"),
                        reset_after=item.get("reset_after_seconds"),
                    ))
        benefits = []
        if usage:
            reset_credits = usage.get("rate_limit_reset_credits")
            if reset_credits is not None and "available_count" in reset_credits:
                count = int(reset_credits.get("available_count") or 0)
                benefits.append({
                    "label": "리셋 크레딧",
                    "amount": f"{count}개",
                    "detail": "Codex 제공",
                    "isExpiringSoon": False,
                })
            credits = usage.get("credits") or {}
            if credits.get("has_credits"):
                benefits.append({
                    "label": "추가 크레딧",
                    "amount": str(credits.get("balance", "0")),
                    "detail": "현재 잔액",
                    "isExpiringSoon": False,
                })
        account_id = f"codex-{stored['id']}"
        health = _health(get_codex_token_status(stored)) if auth_matches else "unavailable"
        accounts.append({
            "id": account_id,
            "name": info.get("name") or stored.get("name") or stored["id"],
            "email": info.get("email") or stored.get("email", ""),
            "plan": info.get("plan") or stored.get("plan", "?"),
            "health": health,
            "switchable": health == "ready",
            "usage": windows,
            "benefits": benefits,
            "origin": "live",
        })
        if current and auth_matches:
            active_id = account_id
    return _provider("codex", active_id, accounts, "Codex usage + reset credits")


def _strip_terminal_control(text: str) -> str:
    text = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", text)
    return re.sub(r"\x1b\][^\x07]*(?:\x07|\x1b\\)", "", text)


def _parse_grok_usage_text(raw: str):
    text = _strip_terminal_control(raw)
    match = re.search(
        r"Weekly\s+limit(?:\s*\(([^)]+)\))?[\s\S]{0,500}?(\d+(?:\.\d+)?)%[\s\S]{0,500}?Resets:\s*([A-Za-z]+\s+\d{1,2},\s*\d{1,2}:\d{2})",
        text,
        re.IGNORECASE,
    )
    if not match:
        return None
    plan = (match.group(1) or "Grok").strip()
    used = float(match.group(2))
    reset_at = None
    try:
        now = datetime.now().astimezone()
        parsed = datetime.strptime(f"{now.year} {match.group(3)}", "%Y %B %d, %H:%M")
        reset_at = parsed.replace(tzinfo=now.tzinfo)
        if reset_at < now and now - reset_at > timedelta(days=180):
            reset_at = reset_at.replace(year=now.year + 1)
    except ValueError:
        pass
    return {
        "plan": plan,
        **_window("주간", used, reset_at),
    }


def _run_grok_usage(grok_home=None, timeout=12):
    executable = shutil.which("grok") or str(Path.home() / ".grok/bin/grok")
    if not Path(executable).is_file():
        return None
    master_fd, slave_fd = pty.openpty()
    try:
        import fcntl

        fcntl.ioctl(slave_fd, termios.TIOCSWINSZ, struct.pack("HHHH", 28, 110, 0, 0))
        env = os.environ.copy()
        env.setdefault("TERM", "xterm-256color")
        if grok_home:
            env["GROK_HOME"] = str(grok_home)
        process = subprocess.Popen(
            [executable, "--no-alt-screen"],
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=slave_fd,
            env=env,
            close_fds=True,
        )
        os.close(slave_fd)
        slave_fd = -1
        output = bytearray()
        sent = False
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            readable, _, _ = select.select([master_fd], [], [], 0.25)
            if readable:
                try:
                    chunk = os.read(master_fd, 65536)
                except OSError:
                    break
                if not chunk:
                    break
                output.extend(chunk)
            if not sent and (time.monotonic() > deadline - timeout + 1.0 or output):
                os.write(master_fd, b"/usage show\r")
                sent = True
            decoded = output.decode("utf-8", errors="ignore")
            parsed = _parse_grok_usage_text(decoded)
            if parsed:
                return parsed
        return _parse_grok_usage_text(output.decode("utf-8", errors="ignore"))
    finally:
        if "process" in locals() and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=1)
        os.close(master_fd)
        if slave_fd >= 0:
            os.close(slave_fd)


def _safe_grok_usage(grok_home):
    for timeout in (12, 6):
        try:
            usage = _run_grok_usage(grok_home, timeout=timeout)
        except (OSError, subprocess.SubprocessError):
            usage = None
        if usage is not None:
            return usage
    return None


def grok_provider() -> dict:
    from claude_account_manager.grok_profiles import get_grok_launch_contract, list_grok_profiles

    profiles = list_grok_profiles()
    contracts = []
    for profile in profiles:
        profile_id = str(profile["accountID"])
        try:
            contract = get_grok_launch_contract(profile_id)
            grok_home = str(contract["environment"]["GROK_HOME"])
        except (KeyError, TypeError, ValueError):
            continue
        contracts.append((profile_id, grok_home))
    with ThreadPoolExecutor(max_workers=min(4, max(1, len(contracts)))) as executor:
        futures = {
            grok_home: executor.submit(_safe_grok_usage, grok_home)
            for _, grok_home in contracts
        }
        usage_by_home = {grok_home: future.result() for grok_home, future in futures.items()}
    accounts = []
    current_home = str(Path(os.environ.get("GROK_HOME", str(Path.home() / ".grok"))).expanduser())
    for profile_id, grok_home in contracts:
        usage = usage_by_home.get(grok_home)
        accounts.append({
            "id": f"grok-{profile_id}",
            "name": "기본 프로필" if profile_id == "default" else f"Grok 프로필 · {profile_id}",
            "email": "",
            "plan": usage.get("plan") if usage else "로그인된 GROK_HOME 프로필",
            "health": "ready" if usage else "unavailable",
            "switchable": False,
            "usage": [{key: usage[key] for key in ("label", "usedPercent", "resetsIn")}] if usage else [],
            "benefits": [{
                "label": "사용 한도 재설정",
                "amount": "상태 알 수 없음",
                "detail": "웹에서 확인/적용",
                "isExpiringSoon": False,
            }],
            "origin": "live",
            "grokHome": grok_home,
        })
    active_id = next((account["id"] for account in accounts if account["grokHome"] == current_home), "")
    if profiles:
        note = "Grok 프로필별 /usage 실측 · 기존 세션 전환은 지원하지 않음 · 각 프로필에서 새 GROK_HOME 세션 실행 가능"
    else:
        note = "Grok 로그인 프로필 없음"
    return _provider("grok", active_id, accounts, note)


def _agy_command(command: str, timeout=15):
    executable = shutil.which("agy") or str(Path.home() / ".local/bin/agy")
    if not Path(executable).is_file():
        return None
    try:
        result = subprocess.run(
            [executable, "--print", command, "--output-format", "json"],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        payload = json.loads(result.stdout)
        if result.returncode == 0 and payload.get("status") == "SUCCESS":
            return payload
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError):
        pass
    return None


def _parse_agy_snapshot(usage_payload, credits_payload):
    groups = (((usage_payload or {}).get("command") or {}).get("data") or {}).get("groups") or []
    gemini_group = next((group for group in groups if group.get("name") == "Gemini Models"), None)
    windows = []
    if gemini_group:
        for bucket in gemini_group.get("buckets") or []:
            bucket_id = str(bucket.get("id", ""))
            label = "5시간" if "5h" in bucket_id else "주간" if "weekly" in bucket_id else None
            remaining = bucket.get("remaining_fraction")
            if label and remaining is not None:
                windows.append(_window(
                    label,
                    (1 - float(remaining)) * 100,
                    _parse_iso_datetime(bucket.get("reset_time")),
                ))
    order = {"5시간": 0, "주간": 1}
    windows.sort(key=lambda item: order.get(item["label"], 99))
    benefits = []
    credits_data = (((credits_payload or {}).get("command") or {}).get("data") or {})
    if "remaining_credits" in credits_data:
        benefits.append({
            "label": "AGY 크레딧",
            "amount": str(credits_data.get("remaining_credits") or 0),
            "detail": "Antigravity 제공",
            "isExpiringSoon": False,
        })
    return windows, benefits


def gemini_provider() -> dict:
    with ThreadPoolExecutor(max_workers=2) as executor:
        usage_future = executor.submit(_agy_command, "/usage")
        credits_future = executor.submit(_agy_command, "/credits")
        usage_payload = usage_future.result()
        credits_payload = credits_future.result()
    windows, benefits = _parse_agy_snapshot(usage_payload, credits_payload)
    accounts = []
    active_id = ""
    if usage_payload or credits_payload:
        health = "ready" if usage_payload else "unavailable"
        accounts.append({
            "id": "gemini-agy",
            "name": "Antigravity",
            "email": "AGY 로그인",
            "plan": "Gemini Models",
            "health": health,
            "switchable": False,
            "usage": windows,
            "benefits": benefits,
            "origin": "live",
        })
        if health == "ready":
            active_id = "gemini-agy"
    return _provider(
        "gemini",
        active_id,
        accounts,
        "AGY /usage + /credits · 레거시 Gemini CLI 메타데이터 미사용",
    )


def _provider(provider_id: str, active: str, accounts, note: str) -> dict:
    return {
        "id": provider_id,
        "activeAccountID": active,
        "accounts": accounts,
        "checkedAt": datetime.now().strftime("%H:%M"),
        "note": note,
    }


def main() -> None:
    providers = []
    loaders = (claude_provider, codex_provider)
    for loader in loaders:
        try:
            providers.append(loader())
        except Exception as exc:
            name = loader.__name__
            provider_id = name[:-len("_provider")] if name.endswith("_provider") else name
            providers.append(_provider(provider_id, "", [], f"조회 실패 · {type(exc).__name__}"))
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [(loader, executor.submit(loader)) for loader in (grok_provider, gemini_provider)]
        for loader, future in futures:
            try:
                providers.append(future.result())
            except Exception as exc:
                name = loader.__name__
                provider_id = name[:-len("_provider")] if name.endswith("_provider") else name
                providers.append(_provider(provider_id, "", [], f"조회 실패 · {type(exc).__name__}"))
    snapshot = {"capturedAt": datetime.now(timezone.utc).isoformat(), "providers": providers}
    print(json.dumps(snapshot, ensure_ascii=False))


if __name__ == "__main__":
    main()
