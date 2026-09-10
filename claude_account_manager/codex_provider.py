from __future__ import annotations

"""Codex 계정 통합 브리지 — ~/.codex/auth.json 읽기/쓰기"""
from pathlib import Path
import json, os
import re


_ACCOUNT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


def _atomic_write_json(path: Path, data: dict) -> bool:
    """Write private JSON without exposing partial content at the final path."""
    import tempfile

    temporary_path = None
    descriptor = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_path = tempfile.mkstemp(
            dir=str(path.parent), prefix=".%s." % path.name
        )
        with os.fdopen(descriptor, "w", encoding="utf-8") as temporary:
            descriptor = None
            json.dump(data, temporary, indent=2, ensure_ascii=False)
            temporary.flush()
            os.fsync(temporary.fileno())
        os.chmod(temporary_path, 0o600)
        os.replace(temporary_path, path)
        temporary_path = None
        return True
    except (OSError, TypeError, ValueError):
        return False
    finally:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass
        if temporary_path is not None:
            try:
                os.unlink(temporary_path)
            except OSError:
                pass


def _decode_jwt_payload(token: str) -> dict:
    """JWT 페이로드(중간 segment) base64 디코딩. 실패 시 {}."""
    try:
        import base64
        parts = token.split(".")
        if len(parts) < 2:
            return {}
        pad = parts[1] + "=="
        return json.loads(base64.urlsafe_b64decode(pad))
    except Exception:
        return {}


def get_codex_auth_info(auth: dict) -> dict:
    """access_token/id_token JWT에서 name, email, plan 추출."""
    tokens = auth.get("tokens", {}) if auth else {}
    info = {}
    at = _decode_jwt_payload(tokens.get("access_token", ""))
    it = _decode_jwt_payload(tokens.get("id_token", ""))

    info["email"] = (
        at.get("https://api.openai.com/profile", {}).get("email")
        or it.get("email")
        or ""
    )
    info["name"] = it.get("name") or info["email"].split("@")[0] if info["email"] else ""
    raw_plan = at.get("https://api.openai.com/auth", {}).get("chatgpt_plan_type", "")
    info["plan"] = raw_plan.capitalize() if raw_plan else "Free"
    return info

CODEX_DIR = Path.home() / ".codex"
CODEX_AUTH_FILE = CODEX_DIR / "auth.json"
CODEX_ACCOUNTS_DIR = CODEX_DIR / "accounts"
CODEX_INDEX_FILE = CODEX_ACCOUNTS_DIR / "index.json"


def is_codex_available() -> bool:
    """Codex 연동 가능 여부 — 저장된 계정 인덱스 또는 현재 CLI 로그인이 있으면 True.

    인덱스만 보면 새 머신에서 첫 계정을 등록할 수 없다(인덱스는 등록해야
    생기는데 등록 메뉴가 인덱스 존재에 가려짐). auth.json(Codex CLI 로그인)도
    가용 신호로 취급해 첫 등록 경로를 연다.
    """
    return CODEX_INDEX_FILE.exists() or CODEX_AUTH_FILE.exists()


def load_codex_index() -> dict:
    try:
        return json.loads(CODEX_INDEX_FILE.read_text())
    except Exception:
        return {"accounts": []}


def read_codex_auth(auth_file: Path = None) -> dict | None:
    path = auth_file or CODEX_AUTH_FILE
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def write_codex_auth(data: dict, auth_file: Path = None) -> bool:
    path = auth_file or CODEX_AUTH_FILE
    return _atomic_write_json(path, data)


def get_current_codex_account_id() -> str | None:
    """현재 활성 Codex 계정의 account_id 반환"""
    auth = read_codex_auth()
    if not auth:
        return None
    return auth.get("tokens", {}).get("account_id")


def _auth_generation(auth: dict | None) -> tuple[int, str]:
    """auth 스냅샷의 세대 — (access_token exp, last_refresh). 클수록 최신."""
    tokens = auth.get("tokens", {}) if auth else {}
    raw_exp = _decode_jwt_payload(tokens.get("access_token", "") or "").get("exp")
    try:
        exp = int(raw_exp)
    except (TypeError, ValueError):
        exp = 0
    return exp, str((auth or {}).get("last_refresh") or "")


def sync_active_codex_snapshot() -> str | None:
    """활성 auth.json을 소유 계정 스냅샷(auth_{id}.json)에 되쓴다.

    Codex CLI는 ~/.codex/auth.json만 갱신하고, 갱신할 때 refresh_token이
    회전한다. 스냅샷을 따라 갱신하지 않으면 다른 계정으로 로그인/전환한 뒤
    이전 계정 스냅샷에는 만료된 access_token과 이미 소진된 refresh_token만
    남아 실제로 `codex login` 재로그인이 필요해진다. 활성 auth를 읽는 경로마다
    호출해 그 드리프트를 막는다. 반환: 갱신한 계정 id 또는 None.
    """
    live = read_codex_auth()
    if not live:
        return None
    account_id = live.get("tokens", {}).get("account_id")
    if not account_id:
        return None
    stored_id = None
    for acc in load_codex_index().get("accounts", []):
        if acc.get("account_id") == account_id:
            stored_id = acc.get("id")
            break
    if not isinstance(stored_id, str) or not _ACCOUNT_ID.fullmatch(stored_id):
        return None
    snapshot = CODEX_ACCOUNTS_DIR / f"auth_{stored_id}.json"
    if snapshot.is_symlink():
        return None
    stored = read_codex_auth(snapshot)
    if stored == live:
        return None
    # downgrade 금지 — 더 최신인 스냅샷을 오래된 활성 auth로 덮지 않는다.
    if _auth_generation(live) <= _auth_generation(stored):
        return None
    if not write_codex_auth(live, snapshot):
        return None
    return stored_id


def get_codex_token_status(acc: dict) -> str:
    """
    계정의 토큰 상태 반환: 'ok' | 'expiring' | 'expired' | 'no_auth'

    현재 활성 계정이면 ~/.codex/auth.json(Codex CLI가 자동 갱신)을 기준으로
    판정해 실제 갱신 상태를 반영한다. 판정은 access_token JWT의 실제 exp를
    쓰고, exp가 없으면 last_refresh + 240h로 폴백.
    """
    from datetime import datetime, timedelta
    account_id = acc.get("id")
    if not isinstance(account_id, str) or not _ACCOUNT_ID.fullmatch(account_id):
        return "no_auth"
    auth_file = CODEX_ACCOUNTS_DIR / f"auth_{account_id}.json"
    auth = read_codex_auth(auth_file)
    if not auth:
        return "no_auth"
    # 현재 활성 auth.json이 같은 계정이면 실제 갱신 상태를 반영
    active = read_codex_auth()
    if active and active.get("tokens", {}).get("account_id") == acc.get("account_id"):
        auth = active
    now = datetime.utcnow()
    # access_token JWT의 exp 우선 (Codex CLI가 갱신한 실제 만료 시각)
    exp = _decode_jwt_payload(auth.get("tokens", {}).get("access_token", "")).get("exp")
    if exp:
        try:
            expiry = datetime.utcfromtimestamp(exp)
            if now > expiry - timedelta(minutes=5):
                return "expired"
            if now > expiry - timedelta(hours=24):
                return "expiring"
            return "ok"
        except Exception:
            pass
    # 폴백: last_refresh + 240h
    lr = auth.get("last_refresh")
    if not lr:
        return "expired"
    try:
        dt = datetime.strptime(lr[:19], "%Y-%m-%dT%H:%M:%S")
        expiry = dt + timedelta(hours=240)
        if now > expiry - timedelta(minutes=5):
            return "expired"
        if now > expiry - timedelta(hours=24):
            return "expiring"
        return "ok"
    except Exception:
        return "expired"


def switch_codex_account(acc: dict) -> tuple[bool, str]:
    """Codex 계정으로 전환: auth_file → ~/.codex/auth.json 교체"""
    from datetime import datetime
    account_id = acc.get("id")
    if not isinstance(account_id, str) or not _ACCOUNT_ID.fullmatch(account_id):
        return False, "유효하지 않은 Codex 계정 ID입니다"
    # 전환으로 밀려나는 현재 계정의 회전된 refresh_token을 먼저 스냅샷에 보존한다.
    # 대상이 곧 현재 계정이면 이 동기화가 stale 스냅샷을 최신 auth로 끌어올려
    # 아래 write가 live를 과거로 되돌리는 것도 막는다.
    sync_active_codex_snapshot()
    auth_file = CODEX_ACCOUNTS_DIR / f"auth_{account_id}.json"
    if auth_file.is_symlink():
        return False, "심볼릭 링크 인증 파일은 사용할 수 없습니다"
    auth = read_codex_auth(auth_file)
    if not auth:
        return False, f"인증 파일 없음: auth_{account_id}.json"
    expected_account_id = acc.get("account_id")
    stored_account_id = auth.get("tokens", {}).get("account_id")
    if not expected_account_id or stored_account_id != expected_account_id:
        return False, "저장된 auth identity가 계정 인덱스와 일치하지 않습니다"

    # 백업
    backup_dir = CODEX_ACCOUNTS_DIR / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    current = read_codex_auth()
    if current:
        bk = backup_dir / f"auth_{ts}.json"
        write_codex_auth(current, bk)
        # 오래된 백업 정리 (최근 5개)
        backups = sorted(backup_dir.glob("auth_*.json"), key=lambda p: p.stat().st_mtime)
        for old in backups[:-5]:
            try:
                old.unlink()
            except Exception:
                pass

    if write_codex_auth(auth):
        if get_current_codex_account_id() != expected_account_id:
            restored = False
            active_after_write = read_codex_auth()
            # Compare-and-swap rollback: only undo the exact value written by
            # this transaction. A concurrent login/refresh owns any other value.
            if active_after_write == auth:
                if current:
                    restored = write_codex_auth(current)
                else:
                    try:
                        CODEX_AUTH_FILE.unlink()
                        restored = not CODEX_AUTH_FILE.exists()
                    except OSError:
                        restored = False
            elif active_after_write == current:
                restored = True
            else:
                restored = False
            suffix = "" if restored else " (이전 auth 자동 복구 실패)"
            return False, "auth.json 전환 후 readback 불일치%s" % suffix
        # last_used 업데이트
        try:
            index = load_codex_index()
            for a in index["accounts"]:
                if a["id"] == account_id:
                    a["last_used"] = datetime.now().isoformat()
            _atomic_write_json(CODEX_INDEX_FILE, index)
        except Exception:
            pass
        return True, acc.get("name") or account_id
    return False, "auth.json 쓰기 실패"


def fetch_codex_usage(auth: dict) -> dict | None:
    """
    /backend-api/codex/usage 호출. ChatGPT-Account-Id 헤더 필요.
    반환: rate_limit 딕셔너리 또는 None
    """
    import urllib.request, urllib.error
    tokens = auth.get("tokens", {}) if auth else {}
    access_token = tokens.get("access_token", "")
    if not access_token:
        return None
    at = _decode_jwt_payload(access_token)
    account_id = at.get("https://api.openai.com/auth", {}).get("chatgpt_account_id", "")
    try:
        req = urllib.request.Request(
            "https://chatgpt.com/backend-api/codex/usage",
            headers={
                "Authorization": f"Bearer {access_token}",
                "ChatGPT-Account-Id": account_id,
                "User-Agent": "codex-cli/0.128.0",
                # WAF가 originator 헤더 없는 요청을 403 차단 → codex CLI와 동일 헤더 전송
                "originator": "codex_cli_rs",
            },
        )
        with urllib.request.urlopen(req, timeout=5) as r:
            return json.loads(r.read().decode())
    except Exception:
        return None


def add_codex_account(name: str = None) -> tuple[bool, str]:
    """현재 ~/.codex/auth.json을 Codex 계정으로 저장"""
    import hashlib
    from datetime import datetime

    auth = read_codex_auth()
    if not auth:
        return False, "~/.codex/auth.json 없음 — codex login 먼저 실행하세요"

    tokens = auth.get("tokens", {})
    account_id = tokens.get("account_id")
    if not account_id:
        return False, "auth.json에 account_id가 없습니다"

    # 8자리 단축 ID (account_id 해시)
    short_id = hashlib.md5(account_id.encode()).hexdigest()[:8]

    # 중복 확인
    if is_codex_available():
        index = load_codex_index()
        for acc in index.get("accounts", []):
            if acc.get("account_id") == account_id:
                return False, f"이미 등록된 계정입니다: {acc['name']} (id: {acc['id']})"
    else:
        index = {"accounts": []}

    # JWT에서 실제 name, email, plan 추출
    info = get_codex_auth_info(auth)
    if not name:
        name = info.get("name") or info.get("email", "").split("@")[0] or f"codex-{short_id[:4]}"
    email = info.get("email", "")
    plan = info.get("plan", "Free")

    # auth 파일 저장
    CODEX_ACCOUNTS_DIR.mkdir(parents=True, exist_ok=True)
    auth_file = CODEX_ACCOUNTS_DIR / f"auth_{short_id}.json"
    if not write_codex_auth(auth, auth_file):
        return False, "auth 파일 저장 실패"

    # index 업데이트
    now = datetime.now().isoformat()
    index["accounts"].append({
        "id": short_id,
        "name": name,
        "email": email,
        "account_id": account_id,
        "plan": plan,
        "added_at": now,
        "last_used": now,
    })
    try:
        tmp = CODEX_INDEX_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(index, indent=2, ensure_ascii=False))
        tmp.rename(CODEX_INDEX_FILE)
    except Exception as e:
        return False, f"index 저장 실패: {e}"

    return True, f"{name} (id: {short_id})"


def remove_codex_account(acc: dict) -> tuple[bool, str]:
    """저장된 Codex 계정 삭제"""
    # auth 파일 삭제
    auth_file = CODEX_ACCOUNTS_DIR / f"auth_{acc['id']}.json"
    if auth_file.exists():
        auth_file.unlink()
    # index에서 제거
    try:
        index = load_codex_index()
        index["accounts"] = [a for a in index["accounts"] if a["id"] != acc["id"]]
        tmp = CODEX_INDEX_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(index, indent=2, ensure_ascii=False))
        tmp.rename(CODEX_INDEX_FILE)
    except Exception as e:
        return False, str(e)
    return True, acc["name"]
