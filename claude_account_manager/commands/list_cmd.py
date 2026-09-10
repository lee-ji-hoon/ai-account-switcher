"""
cmd_list: Display registered accounts with usage visualization
"""
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from ..config import ACCOUNTS_DIR
from ..ui import c, Colors, make_progress_bar
from ..storage import load_index, get_current_account
from ..keychain import get_keychain_credential
from ..token import TokenStatus
from ..api import _fetch_usage_from_api
from ..account import estimate_plan, is_same_account, _is_real_org


def _get_token_expires_at(credential):
    """credential에서 토큰 만료 시간(datetime) 반환"""
    if not credential:
        return None
    oauth = credential.get("claudeAiOauth", {})
    expires_at = oauth.get("expiresAt")
    if not expires_at:
        return None
    # expiresAt은 밀리초 타임스탬프
    return datetime.fromtimestamp(expires_at / 1000)


def cmd_list():
    """등록된 계정 목록 표시 (사용량 시각화 포함)"""
    index = load_index()
    current = get_current_account()
    current_email = current.get("emailAddress", "")
    current_plan = estimate_plan(current)

    def _is_current(acc):
        return is_same_account(acc, current)

    # 헤더
    print()
    print(c(Colors.BOLD, "  Claude 계정 목록"))
    print(c(Colors.DIM, "  " + "─" * 55))

    if not index["accounts"]:
        print(c(Colors.DIM, "  (등록된 계정 없음)"))
        print(c(Colors.DIM, "  /account add [이름] 으로 현재 계정을 저장하세요"))
    else:
        # 병렬로 모든 계정의 사용량 가져오기
        def fetch_account_usage(acc):
            """계정별 사용량 및 토큰 상태 가져오기 (401 시 자동 갱신 포함)"""
            is_current = _is_current(acc)
            if is_current:
                # 현재 계정: Keychain 사용, credential_file=None
                usage, token_status = _fetch_usage_from_api(include_token_status=True)
                # 현재 계정의 credential에서 만료 시간 가져오기
                current_cred = get_keychain_credential()
                expires_at = _get_token_expires_at(current_cred)
                return (acc["id"], usage, token_status, expires_at)
            else:
                # 저장된 계정: credential 파일 사용
                cred_filename = acc.get("credentialFile")
                if cred_filename:
                    credential_path = ACCOUNTS_DIR / cred_filename
                    if credential_path.exists():
                        try:
                            credential = json.loads(credential_path.read_text())
                            # credential_file 전달하여 401 갱신 시 파일에 저장
                            usage, token_status = _fetch_usage_from_api(
                                credential,
                                include_token_status=True,
                                credential_file=credential_path
                            )
                            # 갱신 후 다시 읽어서 최신 만료 시간 가져오기
                            try:
                                updated_cred = json.loads(credential_path.read_text())
                                expires_at = _get_token_expires_at(updated_cred)
                            except Exception:
                                expires_at = _get_token_expires_at(credential)
                            return (acc["id"], usage, token_status, expires_at)
                        except Exception:
                            pass
                return (acc["id"], None, TokenStatus.NO_TOKEN, None)

        # 계정별 사용량 병렬 조회 (각 계정은 서로 다른 토큰 사용 → rate limit 독립)
        usage_map = {}
        token_status_map = {}
        expires_at_map = {}

        max_workers = min(len(index["accounts"]), 8)
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            for result in executor.map(fetch_account_usage, index["accounts"]):
                try:
                    acc_id, usage, token_status, expires_at = result
                    usage_map[acc_id] = usage
                    token_status_map[acc_id] = token_status
                    expires_at_map[acc_id] = expires_at
                except Exception:
                    pass

        # 결과 출력
        for i, acc in enumerate(index["accounts"], 1):
            is_active = acc["id"] == index.get("activeAccountId")
            is_current = _is_current(acc)

            if is_active and is_current:
                marker = c(Colors.GREEN, "●")
                status = c(Colors.GREEN, "활성")
            elif is_current:
                marker = c(Colors.CYAN, "→")
                status = c(Colors.CYAN, "현재")
            elif is_active:
                marker = c(Colors.DIM, "○")
                status = c(Colors.DIM, "저장됨")
            else:
                marker = " "
                status = ""

            # Plan 정보 가져오기 — API planName 우선 (stale 방지)
            real_usage = usage_map.get(acc["id"])
            api_plan = real_usage.get("planName") if real_usage else None
            if api_plan:
                plan = api_plan
                # 저장된 플랜과 다르면 index 자동 업데이트
                if acc.get("plan") != api_plan:
                    acc["plan"] = api_plan
                    try:
                        from ..storage import save_index
                        save_index(index)
                    except Exception:
                        pass
            elif "plan" in acc:
                plan = acc["plan"]
            elif is_current:
                plan = current_plan
            else:
                profile_path = ACCOUNTS_DIR / acc.get("profileFile", "")
                if profile_path.exists():
                    try:
                        profile = json.loads(profile_path.read_text())
                        plan = estimate_plan(profile)
                    except Exception:
                        plan = "?"
                else:
                    plan = "?"

            # Plan 색상
            plan_colors = {
                "Free": Colors.DIM,
                "Pro": Colors.CYAN,
                "Team": Colors.MAGENTA,
                "Max": Colors.YELLOW,
                "Max5": Colors.YELLOW,
                "Max20": Colors.GREEN,
            }
            plan_badge = c(plan_colors.get(plan, Colors.DIM), f"[{plan}]")

            # 출력: [번호] ● name (org) [Plan] - 상태
            status_text = f" - {status}" if status else ""
            acc_org_name = acc.get("organizationName", "")
            org_badge = f" {c(Colors.MAGENTA, f'@{acc_org_name}')}" if _is_real_org(acc_org_name) else ""
            print(f"  [{i}] {marker} {acc['name']}{org_badge} {plan_badge}{status_text}")
            print(f"      {c(Colors.DIM, acc['email'])}")

            # 사용량 표시 (미리 가져온 데이터 사용)
            token_status = token_status_map.get(acc["id"], TokenStatus.NO_TOKEN)
            expires_at = expires_at_map.get(acc["id"])

            # 토큰 상태에 따른 경고 표시
            if token_status == TokenStatus.EXPIRED:
                print(f"      {c(Colors.RED, '⚠ 토큰 만료')} - {c(Colors.YELLOW, '재로그인 필요')}")
            elif token_status == TokenStatus.INVALID:
                print(f"      {c(Colors.RED, '⚠ 토큰 무효')} - {c(Colors.YELLOW, '재로그인 필요')}")
            elif token_status == TokenStatus.NO_TOKEN:
                print(f"      {c(Colors.DIM, '(credential 없음)')}")
            elif token_status == TokenStatus.ERROR:
                print(f"      {c(Colors.YELLOW, '⚠ 연결 오류')} - {c(Colors.DIM, '네트워크 확인 필요')}")
            elif token_status == TokenStatus.VALID and not real_usage:
                # 토큰은 유효하지만 사용량 조회 실패 (429 rate limit 등)
                if expires_at:
                    now_local = datetime.now()
                    remaining = expires_at - now_local
                    if remaining.total_seconds() > 0:
                        hours = int(remaining.total_seconds() // 3600)
                        minutes = int((remaining.total_seconds() % 3600) // 60)
                        expire_str = f"{hours}h {minutes}m" if hours >= 1 else f"{minutes}m"
                        print(f"      {c(Colors.DIM, '토큰')} {c(Colors.DIM, f'🔑 {expire_str} 후 만료')}")
                else:
                    print(f"      {c(Colors.DIM, '(사용량 조회 일시 실패)')}")
            elif real_usage:
                # 실제 API 데이터 사용
                # API가 반환하는 resetAt은 timezone-aware(UTC)이므로 now도 aware로 생성
                now = datetime.now(timezone.utc)

                # 현재 세션 사용량 (5시간)
                if real_usage["fiveHour"] is not None:
                    percentage = real_usage["fiveHour"]
                    bar = make_progress_bar(percentage, width=12)
                    reset_str = ""
                    if real_usage["fiveHourResetAt"]:
                        remaining = real_usage["fiveHourResetAt"] - now
                        if remaining.total_seconds() > 0:
                            hours = int(remaining.total_seconds() // 3600)
                            minutes = int((remaining.total_seconds() % 3600) // 60)
                            reset_str = f" | {c(Colors.CYAN, '⏱')} {hours}h {minutes}m"
                    print(f"      {c(Colors.DIM, '현재')} {bar} {percentage}%{reset_str}")

                # 주간 사용량
                if real_usage["sevenDay"] is not None:
                    percentage = real_usage["sevenDay"]
                    bar = make_progress_bar(percentage, width=12)
                    reset_str = ""
                    if real_usage["sevenDayResetAt"]:
                        remaining = real_usage["sevenDayResetAt"] - now
                        if remaining.total_seconds() > 0:
                            hours = int(remaining.total_seconds() // 3600)
                            minutes = int((remaining.total_seconds() % 3600) // 60)
                            reset_str = f" | {c(Colors.CYAN, '⏱')} {hours}h {minutes}m"
                    print(f"      {c(Colors.DIM, '주간')} {bar} {percentage}%{reset_str}")

                # 토큰 만료 시간 표시
                if expires_at:
                    now_local = datetime.now()
                    remaining = expires_at - now_local
                    if remaining.total_seconds() > 0:
                        hours = int(remaining.total_seconds() // 3600)
                        minutes = int((remaining.total_seconds() % 3600) // 60)
                        # 1시간 이내면 경고 색상
                        if hours < 1:
                            expire_color = Colors.YELLOW
                            expire_str = f"{minutes}m"
                        else:
                            expire_color = Colors.DIM
                            expire_str = f"{hours}h {minutes}m"
                        print(f"      {c(Colors.DIM, '토큰')} {c(expire_color, f'🔑 {expire_str} 후 만료')}")

    # Codex 섹션
    from ..codex_provider import (
        is_codex_available, load_codex_index, get_current_codex_account_id,
        get_codex_token_status, CODEX_ACCOUNTS_DIR, read_codex_auth, get_codex_auth_info,
        fetch_codex_usage, sync_active_codex_snapshot,
    )

    def _disp_len(s):
        import unicodedata
        return sum(2 if unicodedata.east_asian_width(ch) in ('W', 'F') else 1 for ch in s)

    def _pad_label(s, width):
        return s + ' ' * max(0, width - _disp_len(s))

    def _codex_window_label(window):
        try:
            seconds = int(window.get("limit_window_seconds"))
        except (TypeError, ValueError):
            return "제한"
        windows = (
            (18000, "5h"),
            (86400, "일간"),
            (604800, "주간"),
            (2592000, "월간"),
            (31536000, "연간"),
        )
        for expected, label in windows:
            if abs(seconds - expected) <= expected * 0.05:
                return label
        return "제한"

    def _print_codex_usage_rows(rows):
        """rows: list of (label, window_dict). 레이블 너비 자동 정렬."""
        if not rows:
            return
        max_w = max(_disp_len(label) for label, _ in rows)
        for label, window in rows:
            try:
                used_pct = float(window.get("used_percent", 0))
            except (TypeError, ValueError):
                used_pct = 0.0
            bar = make_progress_bar(used_pct, width=12)
            try:
                reset_seconds = int(window.get("reset_after_seconds", 0))
            except (TypeError, ValueError):
                reset_seconds = 0
            reset_suffix = ""
            if reset_seconds > 0:
                hours = reset_seconds // 3600
                minutes = (reset_seconds % 3600) // 60
                reset_suffix = f" | {c(Colors.CYAN, '⏱')} {hours}h {minutes}m"
            padded = _pad_label(label, max_w)
            print(f"      {c(Colors.DIM, padded)} {bar} {used_pct:g}%{reset_suffix}")

    claude_count = len(index["accounts"])

    if is_codex_available():
        # 목록을 그리기 전에 Codex CLI가 갱신한 활성 auth를 소유 계정 스냅샷에 반영한다.
        sync_active_codex_snapshot()
        codex_index = load_codex_index()
        codex_accounts = codex_index.get("accounts", [])
        if codex_accounts:
            current_codex_id = get_current_codex_account_id()
            print()
            print(f"  {c(Colors.DIM, 'Codex')}")
            for j, acc in enumerate(codex_accounts, claude_count + 1):
                is_current = acc.get("account_id") == current_codex_id
                marker = c(Colors.GREEN, "●") if is_current else " "

                # JWT에서 실시간 name/email/plan 추출 (저장된 값 fallback)
                auth_file = CODEX_ACCOUNTS_DIR / f"auth_{acc['id']}.json"
                auth_data = read_codex_auth() if is_current else read_codex_auth(auth_file)
                if not auth_data and is_current:
                    auth_data = read_codex_auth(auth_file)
                if auth_data:
                    info = get_codex_auth_info(auth_data)
                    display_name = info.get("name") or acc.get("name", acc["id"])
                    display_email = info.get("email") or acc.get("email", "")
                    plan = info.get("plan") or acc.get("plan", "?")
                else:
                    display_name = acc.get("name", acc["id"])
                    display_email = acc.get("email", "")
                    plan = acc.get("plan", "?")

                plan_colors = {"Pro": Colors.CYAN, "Plus": Colors.CYAN, "Free": Colors.DIM}
                plan_badge = c(plan_colors.get(plan, Colors.DIM), f"[{plan}]")
                status_str = c(Colors.GREEN, "활성") if is_current else ""
                status_text = f" - {status_str}" if status_str else ""
                print(f"  [{j}] {marker} {display_name} {plan_badge}{status_text}")
                if display_email:
                    print(f"      {c(Colors.DIM, display_email)}")

                # 사용량 조회 (auth_data 있는 경우) — 레이블 모아서 한번에 정렬 출력
                usage_data = fetch_codex_usage(auth_data) if auth_data else None
                if usage_data:
                    rows = []
                    rl = usage_data.get("rate_limit") or {}
                    for key in ("primary_window", "secondary_window"):
                        window = rl.get(key)
                        if window:
                            rows.append((_codex_window_label(window), window))
                    for extra in usage_data.get("additional_rate_limits") or []:
                        short_name = extra.get("limit_name", "") or ""
                        if "Spark" in short_name:
                            continue
                        short_name = short_name.replace("GPT-5.3-Codex-", "").replace("GPT-5-Codex-", "")
                        erl = extra.get("rate_limit") or {}
                        for key in ("primary_window", "secondary_window"):
                            window = erl.get(key)
                            if window:
                                label = f"{short_name} {_codex_window_label(window)}".strip()
                                rows.append((label, window))
                    _print_codex_usage_rows(rows)

                ts = get_codex_token_status(acc)
                if ts == "expired":
                    print(f"      {c(Colors.RED, '⚠ 토큰 만료')} - {c(Colors.YELLOW, 'codex login 필요')}")
                elif ts == "expiring":
                    print(f"      {c(Colors.YELLOW, '⚠ 24시간 내 만료')}")
                elif ts == "no_auth":
                    print(f"      {c(Colors.DIM, '(인증 파일 없음)')}")
                else:
                    if auth_data and auth_data.get("last_refresh"):
                        try:
                            from datetime import timedelta as _td
                            dt = datetime.strptime(auth_data["last_refresh"][:19], "%Y-%m-%dT%H:%M:%S")
                            expiry = dt + _td(hours=240)
                            remaining = expiry - datetime.utcnow()
                            days = int(remaining.total_seconds() // 86400)
                            hrs = int((remaining.total_seconds() % 86400) // 3600)
                            expire_color = Colors.YELLOW if days < 1 else Colors.DIM
                            print(f"      {c(Colors.DIM, '토큰')} {c(expire_color, f'🔑 {days}d {hrs}h 후 만료')}")
                        except Exception:
                            pass

    # ── Grok (x.ai) ────────────────────────────────────────────────
    # 사용량 %·재설정 시각은 API가 없어(실측: /v1/usage 등 404) 가져오지 못한다.
    # 대신 최소 요청 1회로 "지금 쓸 수 있나"를 판정한다 — 403 spending-limit은
    # 인증 실패가 아니라 한도 소진이라, 구분해야 재로그인 삽질을 막는다.
    from ..grok_provider import (
        is_grok_available, load_grok_accounts, get_grok_token_status,
        probe_grok_entitlement, STATUS_LABELS, GROK_USAGE_URL,
    )

    if is_grok_available():
        grok_accounts = load_grok_accounts()
        if grok_accounts:
            print()
            print(f"  {c(Colors.DIM, 'Grok')}")
            for acc in grok_accounts:
                label = acc.get("name") or acc.get("email") or "(unknown)"
                print(f"    {c(Colors.CYAN, label)} {c(Colors.DIM, acc.get('email', ''))}")

                state, detail = probe_grok_entitlement(acc.get("access_token", ""))
                text = STATUS_LABELS.get(state, state)
                if state == "ok":
                    print(f"      {c(Colors.GREEN, '● ' + text)}")
                elif state == "quota_exhausted":
                    print(f"      {c(Colors.RED, '● ' + text)} - {c(Colors.YELLOW, GROK_USAGE_URL)}")
                    print(f"      {c(Colors.DIM, '재설정 시각·일회성 리셋 티켓은 위 페이지에서만 확인된다')}")
                elif state == "unauthorized":
                    print(f"      {c(Colors.RED, '● ' + text)} - {c(Colors.YELLOW, 'grok 재로그인 필요')}")
                else:
                    print(f"      {c(Colors.DIM, '● ' + text)} {c(Colors.DIM, detail[:60])}")

                ts = get_grok_token_status(acc)
                if ts == "expired":
                    print(f"      {c(Colors.DIM, '토큰')} {c(Colors.DIM, '만료 — grok CLI 실행 시 자동 갱신')}")
                elif ts == "expiring":
                    print(f"      {c(Colors.DIM, '토큰')} {c(Colors.YELLOW, '1시간 내 만료')}")

    print(c(Colors.DIM, "  " + "─" * 55))

    if not current_email:
        print()
        print(c(Colors.YELLOW, "  현재 로그인된 계정이 없습니다."))

    print()
