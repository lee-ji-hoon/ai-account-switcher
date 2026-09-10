"""grok(x.ai) 계정 통합 — ~/.grok/auth.json 읽기 + 라이브 entitlement 프로브.

**사용량 조회 API는 없다(실측 2026-08-18).** `/v1/usage`·`/v1/rate-limits`·
`/v1/billing/usage`는 전부 404이고, `/v1/api-key`는 OAuth 토큰에 401을 준다.
주간 SuperGrok 한도 %, 재설정 시각, 일회성 "사용 한도 재설정" 티켓은 grok.com
웹 세션에서만 보이므로 여기서는 가져올 수 없다.

가져올 수 있는 것은 **최소 요청 1회의 응답 코드**다. 이게 실무에서 중요한 질문
("지금 grok을 쓸 수 있나?")에 정확히 답한다:

    403 personal-team-blocked:spending-limit → 주간 한도 소진 (인증 실패 아님)
    401                                      → 토큰 문제 (재로그인 필요)
    200                                      → 사용 가능

이 구분이 없으면 한도 소진을 인증 실패로 오진해 재로그인·토큰 갱신으로 시간을
버린다 — 실제로 그렇게 샜다.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

GROK_DIR = Path.home() / ".grok"
GROK_AUTH_FILE = GROK_DIR / "auth.json"
XAI_API_BASE = "https://api.x.ai/v1"
GROK_USAGE_URL = "https://grok.com/?_s=usage"

_ISSUER_PREFIX = "https://auth.x.ai"


def is_grok_available(auth_file: Path | None = None) -> bool:
    return (auth_file or GROK_AUTH_FILE).exists()


def read_grok_auth(auth_file: Path | None = None) -> dict:
    path = auth_file or GROK_AUTH_FILE
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def load_grok_accounts(auth_file: Path | None = None) -> list[dict]:
    """auth.json의 issuer-keyed 엔트리를 계정 목록으로 편다.

    키 형식: ``https://auth.x.ai::<oidc_client_id>``
    """
    data = read_grok_auth(auth_file)
    accounts: list[dict] = []
    for key, entry in data.items():
        if not isinstance(entry, dict):
            continue
        if not key.startswith(_ISSUER_PREFIX):
            continue
        name = " ".join(p for p in (entry.get("first_name"), entry.get("last_name")) if p).strip()
        accounts.append({
            "key": key,
            "email": entry.get("email") or "",
            "name": name or (entry.get("email") or "").split("@")[0],
            "user_id": entry.get("user_id") or "",
            "team_id": entry.get("team_id") or "",
            "expires_at": entry.get("expires_at") or "",
            "access_token": entry.get("key") or "",
            "auth_mode": entry.get("auth_mode") or "",
        })
    return accounts


def _parse_iso(ts: str) -> datetime | None:
    if not ts:
        return None
    raw = ts.rstrip("Z")
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(raw, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def get_grok_token_status(entry: dict) -> str:
    """'ok' | 'expiring' | 'expired' | 'unknown'.

    grok CLI가 access token을 6시간 주기로 갱신하므로 만료가 잦다 — 만료 자체는
    보통 문제가 아니고, CLI를 한 번 돌리면 갱신된다.
    """
    expiry = _parse_iso(entry.get("expires_at") or "")
    if expiry is None:
        return "unknown"
    now = datetime.now(timezone.utc)
    if now >= expiry - timedelta(minutes=5):
        return "expired"
    if now >= expiry - timedelta(hours=1):
        return "expiring"
    return "ok"


def probe_grok_entitlement(token: str, *, timeout: int = 30) -> tuple[str, str]:
    """최소 요청 1회로 지금 grok을 쓸 수 있는지 판정한다.

    Returns (state, detail) — state는
    'ok' | 'quota_exhausted' | 'unauthorized' | 'forbidden' | 'no_credential' | 'error'.
    """
    if not token:
        return "no_credential", "저장된 access token이 없다 (grok CLI 로그인 필요)"

    body = json.dumps({
        "model": os.environ.get("GROK_PROBE_MODEL", "grok-4.6"),
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 1,
    }).encode("utf-8")
    req = urllib.request.Request(
        f"{XAI_API_BASE}/chat/completions", data=body,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            resp.read()
        return "ok", "사용 가능"
    except urllib.error.HTTPError as exc:
        try:
            detail = exc.read().decode("utf-8", "replace")
        except Exception:
            detail = ""
        if exc.code == 401:
            return "unauthorized", "토큰이 거부됐다 — grok CLI 재로그인 필요"
        if exc.code in (402, 403) and (
            "spending-limit" in detail or "credits" in detail or "subscription" in detail
        ):
            return "quota_exhausted", (
                f"주간 한도/크레딧 소진 — 재설정 시각과 일회성 리셋 티켓은 {GROK_USAGE_URL} "
                "에서 확인(사용량 API는 없다). 인증 문제가 아니므로 재로그인은 소용없다."
            )
        if exc.code == 403:
            return "forbidden", f"403이지만 한도 사유가 아님: {detail[:200]}"
        return "error", f"HTTP {exc.code}: {detail[:200]}"
    except Exception as exc:  # noqa: BLE001
        return "error", f"{type(exc).__name__}: {exc}"


STATUS_LABELS = {
    "ok": "사용 가능",
    "quota_exhausted": "주간 한도 소진",
    "unauthorized": "재로그인 필요",
    "forbidden": "접근 거부",
    "no_credential": "로그인 안 됨",
    "error": "확인 실패",
}
