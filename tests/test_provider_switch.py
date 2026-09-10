import json
import os
from pathlib import Path
import hashlib
import subprocess
import sys
import tempfile
import unittest

from unittest import mock

from claude_account_manager.grok_profiles import (
    get_grok_launch_contract,
    list_grok_profiles,
)
from claude_account_manager import codex_provider
from claude_account_manager import provider_switch


REPO_ROOT = Path(__file__).resolve().parents[1]
ENTRYPOINT = REPO_ROOT / "account_manager.py"
RESULT_KEYS = {
    "ok",
    "provider",
    "requestedAccountID",
    "activeAccountID",
    "restartRequired",
    "message",
}


class ProviderSwitchCliTest(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.home = Path(self.temporary_directory.name)
        self.environment = os.environ.copy()
        self.environment.update(
            {
                "HOME": str(self.home),
                "USER": "switchboard-test",
                "PYTHONPATH": str(REPO_ROOT),
            }
        )

    def tearDown(self):
        self.temporary_directory.cleanup()

    def run_switch(self, provider, account_id, extra_environment=None):
        environment = dict(self.environment)
        if extra_environment:
            environment.update(extra_environment)
        completed = subprocess.run(
            [
                sys.executable,
                str(ENTRYPOINT),
                "switch-provider",
                provider,
                account_id,
                "--json",
            ],
            cwd=str(REPO_ROOT),
            env=environment,
            capture_output=True,
            text=True,
        )
        self.assertEqual("", completed.stderr)
        result = json.loads(completed.stdout)
        self.assertEqual(RESULT_KEYS, set(result))
        return completed, result

    def install_fake_security(self):
        binary_directory = self.home / "bin"
        binary_directory.mkdir()
        security = binary_directory / "security"
        security.write_text(
            """#!/bin/sh
store="$HOME/fake-keychain.json"
case "$1" in
  find-generic-password)
    [ -f "$store" ] || exit 44
    cat "$store"
    ;;
  delete-generic-password)
    if [ "${FAKE_SECURITY_DISCARD_ADD:-0}" != "1" ]; then
      command rm -f "$store"
    fi
    ;;
  add-generic-password)
    value=""
    while [ "$#" -gt 0 ]; do
      if [ "$1" = "-w" ]; then
        shift
        value="$1"
        break
      fi
      shift
    done
    if [ "${FAKE_SECURITY_DISCARD_ADD:-0}" != "1" ]; then
      printf '%s' "$value" > "$store"
    fi
    ;;
  *) exit 64 ;;
esac
"""
        )
        security.chmod(0o755)
        self.environment["PATH"] = "%s:%s" % (
            binary_directory,
            self.environment.get("PATH", ""),
        )

    def write_claude_fixture(self, credential_owner_email="target@example.test"):
        accounts_directory = self.home / ".claude" / "accounts"
        accounts_directory.mkdir(parents=True)
        old_profile = {"emailAddress": "old@example.test"}
        target_profile = {"emailAddress": "target@example.test"}
        old_credential = {
            "claudeAiOauth": {
                "accessToken": "old-access",
                "refreshToken": "old-refresh",
                "expiresAt": 4102444800000,
            }
        }
        target_credential = {
            "claudeAiOauth": {
                "accessToken": "target-access",
                "refreshToken": "target-refresh",
                "expiresAt": 4102444800000,
            }
        }
        (self.home / ".claude.json").write_text(
            json.dumps({"oauthAccount": old_profile})
        )
        (self.home / "fake-keychain.json").write_text(json.dumps(old_credential))
        (accounts_directory / "profile_target.json").write_text(
            json.dumps(target_profile)
        )
        credential_path = accounts_directory / "credential_target.json"
        credential_path.write_text(json.dumps(target_credential))
        credential_path.chmod(0o600)
        owner_cache_key = hashlib.sha256(b"target-access").hexdigest()[:16]
        (accounts_directory / ".token-owner-cache.json").write_text(
            json.dumps(
                {
                    owner_cache_key: {
                        "uuid": "target-uuid",
                        "email": credential_owner_email or "",
                        "org_uuid": "",
                    }
                }
            )
        )
        (accounts_directory / "index.json").write_text(
            json.dumps(
                {
                    "version": 1,
                    "activeAccountId": "old",
                    "accounts": [
                        {
                            "id": "target",
                            "name": "Target",
                            "email": "target@example.test",
                            "profileFile": "profile_target.json",
                            "credentialFile": "credential_target.json",
                        }
                    ],
                }
            )
        )
        return old_profile, target_profile, old_credential, target_credential

    def test_claude_switch_succeeds_only_after_profile_and_keychain_readback(self):
        self.install_fake_security()
        _, target_profile, _, target_credential = self.write_claude_fixture()

        completed, result = self.run_switch("claude", "target")

        self.assertEqual(0, completed.returncode)
        self.assertTrue(result["ok"])
        self.assertEqual("claude", result["provider"])
        self.assertEqual("target", result["requestedAccountID"])
        self.assertEqual("target", result["activeAccountID"])
        self.assertTrue(result["restartRequired"])
        current = json.loads((self.home / ".claude.json").read_text())
        self.assertEqual(target_profile, current["oauthAccount"])
        self.assertEqual(
            target_credential,
            json.loads((self.home / "fake-keychain.json").read_text()),
        )
        index = json.loads(
            (self.home / ".claude" / "accounts" / "index.json").read_text()
        )
        self.assertEqual("target", index["activeAccountId"])

    def test_claude_readback_mismatch_fails_and_restores_profile(self):
        self.install_fake_security()
        old_profile, _, old_credential, _ = self.write_claude_fixture()

        completed, result = self.run_switch(
            "claude", "target", {"FAKE_SECURITY_DISCARD_ADD": "1"}
        )

        self.assertNotEqual(0, completed.returncode)
        self.assertFalse(result["ok"])
        self.assertIsNone(result["activeAccountID"])
        current = json.loads((self.home / ".claude.json").read_text())
        self.assertEqual(old_profile, current["oauthAccount"])
        self.assertEqual(
            old_credential,
            json.loads((self.home / "fake-keychain.json").read_text()),
        )

    def test_claude_refuses_valid_credential_owned_by_another_account(self):
        self.install_fake_security()
        old_profile, _, old_credential, _ = self.write_claude_fixture(
            credential_owner_email="other@example.test"
        )

        completed, result = self.run_switch("claude", "target")

        self.assertNotEqual(0, completed.returncode)
        self.assertFalse(result["ok"])
        self.assertIn("소유자", result["message"])
        current = json.loads((self.home / ".claude.json").read_text())
        self.assertEqual(old_profile, current["oauthAccount"])
        self.assertEqual(
            old_credential,
            json.loads((self.home / "fake-keychain.json").read_text()),
        )

    def test_claude_owner_indeterminate_fails_without_mutation(self):
        self.install_fake_security()
        old_profile, _, old_credential, _ = self.write_claude_fixture(
            credential_owner_email=None
        )

        completed, result = self.run_switch("claude", "target")

        self.assertNotEqual(0, completed.returncode)
        self.assertFalse(result["ok"])
        self.assertIn("확인할 수 없어", result["message"])
        current = json.loads((self.home / ".claude.json").read_text())
        self.assertEqual(old_profile, current["oauthAccount"])
        self.assertEqual(
            old_credential,
            json.loads((self.home / "fake-keychain.json").read_text()),
        )

    def test_claude_rollback_never_overwrites_concurrently_rotated_credential(self):
        previous = {"claudeAiOauth": {"refreshToken": "old"}}
        written = {"claudeAiOauth": {"refreshToken": "target"}}
        rotated = {"claudeAiOauth": {"refreshToken": "newer"}}
        with mock.patch.object(provider_switch, "load_claude_json", return_value={"old": 1}), \
             mock.patch.object(provider_switch, "load_index", return_value={"old": 1}), \
             mock.patch.object(provider_switch, "get_keychain_credential", return_value=rotated), \
             mock.patch.object(provider_switch, "set_keychain_credential") as save_keychain:
            restored = provider_switch._restore_claude_state(
                {"old": 1}, previous, {"old": 1},
                {"target": 1}, written, {"target": 1},
            )

        self.assertFalse(restored)
        save_keychain.assert_not_called()

    def write_codex_fixture(self, stored_account_id="upstream-target"):
        accounts_directory = self.home / ".codex" / "accounts"
        accounts_directory.mkdir(parents=True)
        old_auth = {"tokens": {"account_id": "upstream-old", "access_token": "old"}}
        target_auth = {
            "tokens": {"account_id": stored_account_id, "access_token": "target"}
        }
        (self.home / ".codex" / "auth.json").write_text(json.dumps(old_auth))
        (accounts_directory / "auth_target.json").write_text(json.dumps(target_auth))
        (accounts_directory / "index.json").write_text(
            json.dumps(
                {
                    "accounts": [
                        {
                            "id": "target",
                            "name": "Target",
                            "account_id": "upstream-target",
                        }
                    ]
                }
            )
        )
        return old_auth, target_auth

    def test_codex_switch_verifies_registered_and_active_account_ids(self):
        _, target_auth = self.write_codex_fixture()

        completed, result = self.run_switch("codex", "target")

        self.assertEqual(0, completed.returncode)
        self.assertTrue(result["ok"])
        self.assertEqual("target", result["activeAccountID"])
        self.assertTrue(result["restartRequired"])
        self.assertEqual(
            target_auth,
            json.loads((self.home / ".codex" / "auth.json").read_text()),
        )

    def test_codex_refuses_stored_auth_owned_by_another_account(self):
        old_auth, _ = self.write_codex_fixture(stored_account_id="unexpected-owner")

        completed, result = self.run_switch("codex", "target")

        self.assertNotEqual(0, completed.returncode)
        self.assertFalse(result["ok"])
        self.assertIsNone(result["activeAccountID"])
        self.assertEqual(
            old_auth,
            json.loads((self.home / ".codex" / "auth.json").read_text()),
        )

    def test_codex_rollback_never_overwrites_concurrent_login(self):
        old_auth = {"tokens": {"account_id": "old"}}
        target_auth = {"tokens": {"account_id": "target-upstream"}}
        concurrent_auth = {"tokens": {"account_id": "concurrent", "refresh_token": "new"}}
        account = {"id": "target", "account_id": "target-upstream"}
        # 첫 read는 switch 진입부의 스냅샷 동기화가 읽는 활성 auth다. 인덱스를
        # 비워 동기화를 무동작으로 만들고 롤백 경로만 검사한다.
        with tempfile.TemporaryDirectory() as temporary_directory, \
             mock.patch.object(codex_provider, "CODEX_ACCOUNTS_DIR", Path(temporary_directory)), \
             mock.patch.object(codex_provider, "load_codex_index", return_value={"accounts": []}), \
             mock.patch.object(codex_provider, "read_codex_auth", side_effect=[old_auth, target_auth, old_auth, concurrent_auth]), \
             mock.patch.object(codex_provider, "write_codex_auth", return_value=True) as write_auth, \
             mock.patch.object(codex_provider, "get_current_codex_account_id", return_value="concurrent"):
            ok, message = codex_provider.switch_codex_account(account)

        self.assertFalse(ok)
        self.assertIn("복구 실패", message)
        active_writes = [call for call in write_auth.call_args_list if call.args == (target_auth,)]
        self.assertEqual([mock.call(target_auth)], active_writes)
        self.assertNotIn(mock.call(old_auth), write_auth.call_args_list)

    def test_codex_token_status_remains_a_string_for_symlinked_legacy_auth(self):
        with mock.patch.object(
            codex_provider,
            "CODEX_ACCOUNTS_DIR",
            self.home / ".codex" / "accounts",
        ):
            accounts_directory = codex_provider.CODEX_ACCOUNTS_DIR
            accounts_directory.mkdir(parents=True)
            target = self.home / "legacy-auth.json"
            target.write_text("{}")
            (accounts_directory / "auth_legacy.json").symlink_to(target)

            status = codex_provider.get_codex_token_status({"id": "legacy"})

        self.assertIsInstance(status, str)
        self.assertEqual("no_auth", status)

    def test_malformed_provider_index_still_returns_one_fail_closed_json_object(self):
        accounts_directory = self.home / ".codex" / "accounts"
        accounts_directory.mkdir(parents=True)
        (accounts_directory / "index.json").write_text("[]")

        completed, result = self.run_switch("codex", "target")

        self.assertNotEqual(0, completed.returncode)
        self.assertFalse(result["ok"])
        self.assertIsNone(result["activeAccountID"])
        self.assertIn("내부 오류", result["message"])

    def test_grok_returns_a_new_process_launch_contract_not_a_session_switch(self):
        profile_home = self.home / ".grok-profiles" / "work"
        profile_home.mkdir(parents=True)
        (profile_home / "auth.json").write_text("{}")

        completed, result = self.run_switch("grok", "work")

        self.assertNotEqual(0, completed.returncode)
        self.assertFalse(result["ok"])
        self.assertEqual("grok", result["provider"])
        self.assertIsNone(result["activeAccountID"])
        self.assertTrue(result["restartRequired"])
        self.assertIn("GROK_HOME", result["message"])
        self.assertIn("새 Grok", result["message"])

    def test_grok_profile_helpers_only_return_isolated_authenticated_homes(self):
        profiles_root = self.home / "profiles"
        work_home = profiles_root / "work"
        incomplete_home = profiles_root / "incomplete"
        work_home.mkdir(parents=True)
        incomplete_home.mkdir()
        (work_home / "auth.json").write_text("{}")

        with mock.patch.dict(
            os.environ,
            {
                "HOME": str(self.home),
                "SWITCHBOARD_GROK_PROFILES_DIR": str(profiles_root),
            },
        ):
            profiles = list_grok_profiles()
            contract = get_grok_launch_contract("work")
            with self.assertRaises(ValueError):
                get_grok_launch_contract("../escape")

        self.assertEqual(["work"], [item["accountID"] for item in profiles])
        self.assertEqual(
            {"GROK_HOME": str(work_home)}, contract["environment"]
        )
        self.assertEqual("grok", contract["executable"])

    def test_gemini_and_agy_are_explicitly_unsupported(self):
        for provider in ("gemini", "agy"):
            with self.subTest(provider=provider):
                completed, result = self.run_switch(provider, "account")
                self.assertNotEqual(0, completed.returncode)
                self.assertFalse(result["ok"])
                self.assertEqual(provider, result["provider"])
                self.assertIsNone(result["activeAccountID"])
                self.assertFalse(result["restartRequired"])
                self.assertIn("지원하지", result["message"])


if __name__ == "__main__":
    unittest.main()
