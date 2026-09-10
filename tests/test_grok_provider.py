"""grok(x.ai) 계정 provider — 토큰 상태 + 라이브 entitlement 프로브.

왜 프로브인가(실측 2026-08-18): x.ai에는 사용량/한도 조회 API가 없다.
`/v1/usage`·`/v1/rate-limits`·`/v1/billing/usage` 전부 404이고, 주간 한도 %와
재설정 시각, 일회성 "사용 한도 재설정" 티켓은 grok.com 웹 세션에서만 보인다.
대신 **최소 요청 1회의 응답 코드**가 한도 소진 여부를 정확히 알려준다:
403 `personal-team-blocked:spending-limit` = 한도 소진(인증 실패가 아님).
"""
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from claude_account_manager import grok_provider


def _entry(**over):
    base = {
        "key": "header.payload.sig",
        "auth_mode": "oidc",
        "user_id": "u-1",
        "email": "me@example.com",
        "first_name": "지훈",
        "last_name": "이",
        "team_id": "t-1",
        "refresh_token": "r" * 40,
        "expires_at": "2099-01-01T00:00:00.000000Z",
        "oidc_client_id": "c-1",
    }
    base.update(over)
    return base


class GrokAuthReadTest(unittest.TestCase):
    def _auth_file(self, tmp, payload):
        p = Path(tmp) / "auth.json"
        p.write_text(json.dumps(payload), encoding="utf-8")
        return p

    def test_reads_accounts_from_issuer_keyed_entries(self):
        # ~/.grok/auth.json은 "https://auth.x.ai::<client_id>"를 키로 쓴다
        with TemporaryDirectory() as tmp:
            f = self._auth_file(tmp, {"https://auth.x.ai::c-1": _entry()})
            accounts = grok_provider.load_grok_accounts(f)
        self.assertEqual(len(accounts), 1)
        self.assertEqual(accounts[0]["email"], "me@example.com")
        self.assertEqual(accounts[0]["team_id"], "t-1")
        self.assertEqual(accounts[0]["name"], "지훈 이")

    def test_missing_file_yields_empty_list_not_crash(self):
        with TemporaryDirectory() as tmp:
            self.assertEqual(grok_provider.load_grok_accounts(Path(tmp) / "nope.json"), [])

    def test_is_available_reflects_file_presence(self):
        with TemporaryDirectory() as tmp:
            f = self._auth_file(tmp, {"https://auth.x.ai::c-1": _entry()})
            self.assertTrue(grok_provider.is_grok_available(f))
            self.assertFalse(grok_provider.is_grok_available(Path(tmp) / "nope.json"))


class GrokTokenStatusTest(unittest.TestCase):
    def test_expired_when_expires_at_in_past(self):
        self.assertEqual(
            grok_provider.get_grok_token_status(_entry(expires_at="2000-01-01T00:00:00.000000Z")),
            "expired",
        )

    def test_ok_when_far_future(self):
        self.assertEqual(grok_provider.get_grok_token_status(_entry()), "ok")

    def test_expiring_within_one_hour(self):
        from datetime import datetime, timedelta, timezone
        soon = (datetime.now(timezone.utc) + timedelta(minutes=20)).strftime(
            "%Y-%m-%dT%H:%M:%S.%fZ")
        self.assertEqual(grok_provider.get_grok_token_status(_entry(expires_at=soon)), "expiring")

    def test_missing_expiry_is_unknown_not_crash(self):
        e = _entry()
        e.pop("expires_at")
        self.assertEqual(grok_provider.get_grok_token_status(e), "unknown")


class GrokEntitlementProbeTest(unittest.TestCase):
    def _http_error(self, code, body):
        import urllib.error
        return urllib.error.HTTPError(
            "https://api.x.ai/v1/chat/completions", code, "err", {},
            mock.Mock(read=lambda: json.dumps(body).encode("utf-8")))

    def test_probe_ok_on_200(self):
        cm = mock.MagicMock()
        cm.__enter__.return_value = mock.Mock(
            read=lambda: json.dumps({"choices": [{"message": {"content": "hi"}}]}).encode())
        cm.__exit__.return_value = False
        with mock.patch("urllib.request.urlopen", return_value=cm):
            state, detail = grok_provider.probe_grok_entitlement("tok")
        self.assertEqual(state, "ok")

    def test_probe_detects_quota_exhausted_403(self):
        # 이 403은 "재로그인하라"가 아니라 "한도가 찼다"는 뜻 — 구분이 이 함수의 존재 이유다
        err = self._http_error(403, {
            "code": "personal-team-blocked:spending-limit",
            "error": "You have run out of credits or need a Grok subscription.",
        })
        with mock.patch("urllib.request.urlopen", side_effect=err):
            state, detail = grok_provider.probe_grok_entitlement("tok")
        self.assertEqual(state, "quota_exhausted")
        self.assertIn("grok.com", detail)

    def test_probe_reports_unauthorized_401_separately(self):
        err = self._http_error(401, {"error": "invalid token"})
        with mock.patch("urllib.request.urlopen", side_effect=err):
            state, _ = grok_provider.probe_grok_entitlement("tok")
        self.assertEqual(state, "unauthorized")

    def test_probe_without_token_is_no_credential(self):
        state, _ = grok_provider.probe_grok_entitlement("")
        self.assertEqual(state, "no_credential")

    def test_generic_403_is_not_misread_as_quota(self):
        err = self._http_error(403, {"error": "region blocked"})
        with mock.patch("urllib.request.urlopen", side_effect=err):
            state, _ = grok_provider.probe_grok_entitlement("tok")
        self.assertEqual(state, "forbidden")


class GrokUsageDocsTest(unittest.TestCase):
    def test_usage_url_points_at_web_console(self):
        # 사용량 %·재설정 시각·일회성 리셋 티켓은 API에 없다 — 사용자를 웹으로 보낸다
        self.assertIn("grok.com", grok_provider.GROK_USAGE_URL)

    def test_module_states_usage_api_absence(self):
        self.assertIn("404", grok_provider.__doc__ or "")


if __name__ == "__main__":
    unittest.main()
