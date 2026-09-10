"""is_codex_available 게이트 회귀 테스트.

버그: 게이트가 인덱스 존재만 봐서, 새 머신(auth.json만 있음)에서는
/account:add 의 Codex 메뉴가 아예 뜨지 않아 첫 계정을 등록할 수 없었다.
auth.json(현재 Codex CLI 로그인)도 가용 신호여야 한다.
"""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from claude_account_manager import codex_provider


class CodexAvailabilityGateTest(unittest.TestCase):
    def setUp(self):
        # 실제 홈 디렉터리(~/.codex)의 상태가 결과에 새어들지 않도록
        # 모듈 상수 두 개를 모두 임시 경로로 치환한다.
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        base = Path(self._tmp.name)
        self.auth_file = base / "auth.json"
        self.index_file = base / "accounts" / "index.json"
        patchers = [
            patch.object(codex_provider, "CODEX_AUTH_FILE", self.auth_file),
            patch.object(codex_provider, "CODEX_INDEX_FILE", self.index_file),
        ]
        for p in patchers:
            p.start()
            self.addCleanup(p.stop)

    def test_neither_file_means_unavailable(self):
        self.assertFalse(codex_provider.is_codex_available())

    def test_index_only_is_available(self):
        self.index_file.parent.mkdir(parents=True)
        self.index_file.write_text('{"accounts": []}')
        self.assertTrue(codex_provider.is_codex_available())

    def test_auth_only_is_available(self):
        """새 머신 시나리오: CLI 로그인만 있어도 첫 등록 경로가 열려야 한다."""
        self.auth_file.write_text("{}")
        self.assertTrue(codex_provider.is_codex_available())


if __name__ == "__main__":
    unittest.main()
