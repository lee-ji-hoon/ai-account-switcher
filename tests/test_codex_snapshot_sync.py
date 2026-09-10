import base64
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from claude_account_manager import codex_provider


def _token(exp: int) -> str:
    payload = base64.urlsafe_b64encode(json.dumps({"exp": exp}).encode()).decode().rstrip("=")
    return f"header.{payload}.signature"


def _auth(account_id: str, exp: int, last_refresh: str, refresh_token: str) -> dict:
    return {
        "tokens": {
            "access_token": _token(exp),
            "refresh_token": refresh_token,
            "account_id": account_id,
        },
        "last_refresh": last_refresh,
    }


class CodexSnapshotSyncTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        root = Path(self._tmp.name)
        self.accounts_dir = root / "accounts"
        self.accounts_dir.mkdir()
        self.auth_file = root / "auth.json"
        self.index_file = self.accounts_dir / "index.json"
        self.snapshot = self.accounts_dir / "auth_saved1.json"

        for name, value in (
            ("CODEX_DIR", root),
            ("CODEX_AUTH_FILE", self.auth_file),
            ("CODEX_ACCOUNTS_DIR", self.accounts_dir),
            ("CODEX_INDEX_FILE", self.index_file),
        ):
            patcher = patch.object(codex_provider, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

        self.index_file.write_text(
            json.dumps(
                {
                    "accounts": [
                        {"id": "saved1", "account_id": "acct-1", "name": "one"},
                        {"id": "saved2", "account_id": "acct-2", "name": "two"},
                    ]
                }
            )
        )

    def _write(self, path: Path, auth: dict):
        path.write_text(json.dumps(auth))

    def test_rotated_refresh_token_is_written_back_to_snapshot(self):
        self._write(self.snapshot, _auth("acct-1", 1000, "2026-08-18T00:00:00Z", "old-refresh"))
        live = _auth("acct-1", 2000, "2026-09-10T00:00:00Z", "rotated-refresh")
        self._write(self.auth_file, live)

        self.assertEqual(codex_provider.sync_active_codex_snapshot(), "saved1")
        self.assertEqual(json.loads(self.snapshot.read_text()), live)

    def test_missing_snapshot_is_recreated_from_active_auth(self):
        live = _auth("acct-1", 2000, "2026-09-10T00:00:00Z", "rotated-refresh")
        self._write(self.auth_file, live)

        self.assertEqual(codex_provider.sync_active_codex_snapshot(), "saved1")
        self.assertEqual(json.loads(self.snapshot.read_text()), live)

    def test_newer_snapshot_is_never_downgraded_by_older_active_auth(self):
        newer = _auth("acct-1", 3000, "2026-09-10T00:00:00Z", "current-refresh")
        self._write(self.snapshot, newer)
        self._write(self.auth_file, _auth("acct-1", 1000, "2026-08-18T00:00:00Z", "old-refresh"))

        self.assertIsNone(codex_provider.sync_active_codex_snapshot())
        self.assertEqual(json.loads(self.snapshot.read_text()), newer)

    def test_identical_snapshot_is_not_rewritten(self):
        live = _auth("acct-1", 2000, "2026-09-10T00:00:00Z", "same-refresh")
        self._write(self.snapshot, live)
        self._write(self.auth_file, live)
        before = self.snapshot.stat().st_mtime_ns

        self.assertIsNone(codex_provider.sync_active_codex_snapshot())
        self.assertEqual(self.snapshot.stat().st_mtime_ns, before)

    def test_unregistered_active_account_writes_nothing(self):
        self._write(self.auth_file, _auth("acct-unknown", 2000, "2026-09-10T00:00:00Z", "r"))

        self.assertIsNone(codex_provider.sync_active_codex_snapshot())
        self.assertEqual(sorted(p.name for p in self.accounts_dir.iterdir()), ["index.json"])

    def test_symlinked_snapshot_is_refused(self):
        target = Path(self._tmp.name) / "outside.json"
        self._write(target, _auth("acct-1", 1000, "2026-08-18T00:00:00Z", "old-refresh"))
        self.snapshot.symlink_to(target)
        self._write(self.auth_file, _auth("acct-1", 2000, "2026-09-10T00:00:00Z", "rotated"))

        self.assertIsNone(codex_provider.sync_active_codex_snapshot())
        self.assertEqual(
            json.loads(target.read_text())["tokens"]["refresh_token"], "old-refresh"
        )

    def test_switch_preserves_outgoing_rotated_token_before_swapping(self):
        # 활성 계정(acct-1)은 Codex CLI가 갱신해 refresh_token이 회전했지만
        # 스냅샷은 등록 시점 값에 묶여 있다. 전환은 그 회전분을 먼저 보존해야 한다.
        self._write(self.snapshot, _auth("acct-1", 1000, "2026-08-18T00:00:00Z", "old-refresh"))
        self._write(self.auth_file, _auth("acct-1", 2000, "2026-09-10T00:00:00Z", "rotated"))
        target_snapshot = self.accounts_dir / "auth_saved2.json"
        target_auth = _auth("acct-2", 2500, "2026-09-09T00:00:00Z", "two-refresh")
        self._write(target_snapshot, target_auth)

        ok, message = codex_provider.switch_codex_account(
            {"id": "saved2", "account_id": "acct-2", "name": "two"}
        )

        self.assertTrue(ok, message)
        self.assertEqual(
            json.loads(self.snapshot.read_text())["tokens"]["refresh_token"], "rotated"
        )
        self.assertEqual(json.loads(self.auth_file.read_text()), target_auth)

    def test_switch_to_active_account_does_not_rewind_live_auth(self):
        stale = _auth("acct-1", 1000, "2026-08-18T00:00:00Z", "old-refresh")
        live = _auth("acct-1", 2000, "2026-09-10T00:00:00Z", "rotated")
        self._write(self.snapshot, stale)
        self._write(self.auth_file, live)

        ok, message = codex_provider.switch_codex_account(
            {"id": "saved1", "account_id": "acct-1", "name": "one"}
        )

        self.assertTrue(ok, message)
        self.assertEqual(json.loads(self.auth_file.read_text()), live)


if __name__ == "__main__":
    unittest.main()
