import json
import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from claude_account_manager import version as version_module


ROOT = Path(__file__).resolve().parents[1]
DEVELOP_REFSPEC = "+refs/heads/develop:refs/remotes/origin/develop"
MAIN_REFSPEC = "+refs/heads/main:refs/remotes/origin/main"
DEVELOP_CREATE_COMMAND = "git checkout --no-track -b develop origin/develop"
MARKETPLACE_PATH = '$HOME/.claude/plugins/marketplaces/lee-ji-hoon'
MARKETPLACE_CLEAN_GUARD = (
    'test -z "$(git -C "'
    + MARKETPLACE_PATH
    + '" status --porcelain)" || '
    + '{ echo "ERROR: marketplace checkout is not clean" >&2; exit 1; }'
)
MARKETPLACE_EQUALITY_GUARD = (
    'test "$(git -C "'
    + MARKETPLACE_PATH
    + '" rev-parse HEAD)" = "$(git -C "'
    + MARKETPLACE_PATH
    + '" rev-parse origin/main)" || '
    + '{ echo "ERROR: local marketplace main differs from origin/main" >&2; exit 1; }'
)


def run_git(*args, check=True):
    return subprocess.run(
        ["git"] + list(args),
        check=check,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def create_single_branch_marketplace_fixture(root):
    origin = root / "origin.git"
    seed = root / "seed"
    home = root / "home"
    clone = home / ".claude" / "plugins" / "marketplaces" / "lee-ji-hoon"

    run_git("init", "--bare", "-q", str(origin))
    run_git("init", "-q", "-b", "main", str(seed))
    run_git("-C", str(seed), "config", "user.name", "test")
    run_git("-C", str(seed), "config", "user.email", "test@example.invalid")
    run_git("-C", str(seed), "commit", "-q", "--allow-empty", "-m", "initial")
    run_git("-C", str(seed), "remote", "add", "origin", str(origin))
    run_git("-C", str(seed), "push", "-q", "origin", "main")
    clone.parent.mkdir(parents=True)
    run_git(
        "clone",
        "-q",
        "--single-branch",
        "--branch",
        "main",
        str(origin),
        str(clone),
    )
    return origin, seed, home, clone


def create_trackless_develop_fixture(root):
    origin = root / "origin.git"
    seed = root / "seed"
    clone = root / "clone"

    run_git("init", "--bare", "-q", str(origin))
    run_git("init", "-q", "-b", "main", str(seed))
    run_git("-C", str(seed), "config", "user.name", "test")
    run_git("-C", str(seed), "config", "user.email", "test@example.invalid")
    (seed / "tree.txt").write_text("main\n", encoding="utf-8")
    run_git("-C", str(seed), "add", "tree.txt")
    run_git("-C", str(seed), "commit", "-q", "-m", "main")
    main_sha = run_git("-C", str(seed), "rev-parse", "HEAD").stdout.strip()
    run_git("-C", str(seed), "checkout", "-q", "-b", "develop")
    (seed / "tree.txt").write_text("develop\n", encoding="utf-8")
    run_git("-C", str(seed), "commit", "-q", "-am", "develop")
    develop_sha = run_git("-C", str(seed), "rev-parse", "HEAD").stdout.strip()
    run_git("-C", str(seed), "checkout", "-q", "main")
    run_git("-C", str(seed), "remote", "add", "origin", str(origin))
    run_git("-C", str(seed), "push", "-q", "origin", "main", "develop")
    run_git(
        "clone",
        "-q",
        "--single-branch",
        "--branch",
        "main",
        str(origin),
        str(clone),
    )
    return clone, main_sha, develop_sha


def run_release_block(block, home=None, cwd=None):
    env = dict(os.environ)
    if home is not None:
        env["HOME"] = str(home)
    return subprocess.run(
        ["bash"],
        check=False,
        cwd=str(cwd) if cwd is not None else None,
        env=env,
        input=block,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def read_project_version():
    section = None
    versions = []
    for line in (ROOT / "pyproject.toml").read_text(encoding="utf-8").splitlines():
        section_match = re.match(r"^\s*\[([^]]+)]\s*$", line)
        if section_match:
            section = section_match.group(1)
            continue
        if section == "project":
            version_match = re.match(r'^\s*version\s*=\s*["\']([^"\']+)["\']\s*$', line)
            if version_match:
                versions.append(version_match.group(1))

    if len(versions) != 1:
        raise AssertionError(
            "pyproject.toml [project] must contain exactly one literal version entry"
        )
    return versions[0]


def read_release_skill():
    return (ROOT / "skills/release/SKILL.md").read_text(encoding="utf-8")


def release_bash_blocks(release):
    return re.findall(r"```bash\n(.*?)\n```", release, flags=re.DOTALL)


def block_containing(release, marker):
    matches = [block for block in release_bash_blocks(release) if marker in block]
    if len(matches) != 1:
        raise AssertionError(
            "expected exactly one release bash block containing {!r}, found {}".format(
                marker, len(matches)
            )
        )
    return matches[0]


def assert_markers_in_order(test_case, text, markers):
    position = -1
    for marker in markers:
        next_position = text.find(marker, position + 1)
        test_case.assertNotEqual(
            -1,
            next_position,
            "missing or misordered marker {!r}".format(marker),
        )
        position = next_position


class VersionContractTests(unittest.TestCase):
    def test_update_checker_ignores_older_github_release(self):
        response = mock.MagicMock()
        response.status = 200
        response.read.return_value = b'{"tag_name":"v2.5.9"}'
        response.__enter__.return_value = response
        with tempfile.TemporaryDirectory() as temporary_directory, \
             mock.patch.object(version_module, "VERSION_CACHE", Path(temporary_directory) / "cache.json"), \
             mock.patch.object(version_module, "__version__", "2.5.10"), \
             mock.patch.object(version_module.urllib.request, "urlopen", return_value=response):
            self.assertIsNone(version_module.check_for_updates())

    def test_update_checker_accepts_newer_release_from_repository(self):
        response = mock.MagicMock()
        response.status = 200
        response.read.return_value = b'{"tag_name":"v3.0.0"}'
        response.__enter__.return_value = response
        with tempfile.TemporaryDirectory() as temporary_directory, \
             mock.patch.object(version_module, "VERSION_CACHE", Path(temporary_directory) / "cache.json"), \
             mock.patch.object(version_module, "__version__", "2.5.10"), \
             mock.patch.object(version_module.urllib.request, "urlopen", return_value=response):
            self.assertEqual("3.0.0", version_module.check_for_updates())

    def test_runtime_package_and_brand_are_not_confused(self):
        config = (ROOT / "claude_account_manager/config.py").read_text(encoding="utf-8")
        misc = (ROOT / "claude_account_manager/commands/misc_cmd.py").read_text(encoding="utf-8")
        version = (ROOT / "claude_account_manager/version.py").read_text(encoding="utf-8")
        pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        self.assertIn('PACKAGE_NAME = "claude-account-manager"', config)
        self.assertIn('name = "claude-account-manager"', pyproject)
        self.assertNotIn("Claude Account Manager", misc)
        self.assertNotIn("pypi.org", version)
        self.assertIn(
            "https://api.github.com/repos/lee-ji-hoon/ai-account-switcher/releases/latest",
            version,
        )
        self.assertNotIn("pip install --upgrade", version + misc)
        self.assertIn("/plugin update account@lee-ji-hoon", version + misc)

    def test_macos_bundle_version_comes_from_plugin_release_version(self):
        run_script = (ROOT / "prototype/switchboard-menubar/run.sh").read_text(encoding="utf-8")
        self.assertIn('.claude-plugin/plugin.json', run_script)
        self.assertIn('CFBundleShortVersionString', run_script)
        self.assertIn('CFBundleVersion', run_script)

    def test_macos_build_runner_reserves_stdout_for_app_path(self):
        run_script = (ROOT / "prototype/switchboard-menubar/run.sh").read_text(encoding="utf-8")

        self.assertIn("swift build >&2", run_script)
        self.assertIn("printf '%s\\n' \"$APP_DIR\"", run_script)

    def test_macos_build_runner_preserves_build_failure_and_logs(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            bin_directory = Path(temporary_directory) / "bin"
            bin_directory.mkdir()
            swift = bin_directory / "swift"
            swift.write_text(
                "#!/bin/sh\n"
                "echo 'fake build progress'\n"
                "echo 'fake build failure' >&2\n"
                "exit 37\n",
                encoding="utf-8",
            )
            swift.chmod(0o755)
            environment = os.environ.copy()
            environment["PATH"] = "%s:%s" % (bin_directory, environment["PATH"])

            result = subprocess.run(
                [str(ROOT / "prototype/switchboard-menubar/run.sh"), "--build-only"],
                env=environment,
                capture_output=True,
                text=True,
            )

        self.assertEqual(37, result.returncode)
        self.assertEqual("", result.stdout)
        self.assertIn("fake build progress", result.stderr)
        self.assertIn("fake build failure", result.stderr)

    def test_macos_package_uses_release_runner_swift_tools_version(self):
        package = (ROOT / "prototype/switchboard-menubar/Package.swift").read_text(
            encoding="utf-8"
        )
        self.assertIn("// swift-tools-version: 5.10", package)
        self.assertNotIn("// swift-tools-version: 6.0", package)

    def test_tag_workflow_enforces_and_publishes_release_notes(self):
        workflow = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")

        self.assertIn('tags:\n      - "v*.*.*"', workflow)
        self.assertIn(
            'python3 scripts/release_notes.py "$version" --base-ref "$previous_tag" --output release-notes.md',
            workflow,
        )
        self.assertIn("runs-on: macos-14", workflow)
        self.assertIn("prototype/switchboard-menubar/run.sh --build-only", workflow)
        self.assertIn('app_path="$(prototype/switchboard-menubar/run.sh --build-only)"', workflow)
        self.assertNotIn("run.sh --build-only | tail", workflow)
        self.assertIn("codesign --verify --deep --strict", workflow)
        self.assertIn("Switchboard-macos.zip", workflow)
        self.assertIn("actions/upload-artifact@v4", workflow)
        self.assertIn("actions/download-artifact@v4", workflow)
        self.assertIn("needs: build-macos-app", workflow)
        self.assertGreaterEqual(workflow.count('git fetch origin main'), 2)
        self.assertGreaterEqual(workflow.count('git rev-list -n 1 "$GITHUB_REF_NAME"'), 2)
        self.assertGreaterEqual(workflow.count('git rev-parse origin/main'), 2)
        self.assertIn("release tag must point exactly to origin/main", workflow)
        self.assertIn("grep -E '^v[0-9]+\\.[0-9]+\\.[0-9]+$'", workflow)
        self.assertIn("release version must be greater than", workflow)
        self.assertIn("current <= highest", workflow)
        self.assertIn("python3 -m unittest discover -s tests -p 'test_*.py'", workflow)
        self.assertIn(
            "python3 -m unittest discover -s prototype/switchboard-menubar/tests -p 'test_*.py'",
            workflow,
        )
        self.assertIn("bash tests/test_hooks_shell.sh", workflow)
        self.assertIn("bash tests/test_install_shell.sh", workflow)
        self.assertNotIn("gh release upload", workflow)
        self.assertLess(
            workflow.index("python3 -m unittest discover -s tests"),
            workflow.index("gh release create"),
        )
        self.assertLess(
            workflow.index("Build and verify Switchboard.app"),
            workflow.index("gh release create"),
        )
        self.assertLess(
            workflow.index("Switchboard-macos.zip", workflow.index("gh release create")),
            workflow.index("--notes-file release-notes.md"),
        )
        self.assertIn('gh release create "${{ github.ref_name }}"', workflow)
        self.assertIn("--notes-file release-notes.md", workflow)

    def test_release_skill_gates_readme_impact_and_github_release(self):
        release = read_release_skill()

        assert_markers_in_order(
            self,
            release,
            [
                "### Documentation",
                "README 변경 불필요 — <구체적 이유>",
                'python3 scripts/release_notes.py "{version}"',
                '"$PYTHON38" -m unittest discover -s tests -p \'test_*.py\'',
                "git push origin v{version}",
                "gh run watch",
                'gh release view "v{version}"',
            ],
        )

    def test_ci_runs_supported_python_matrix_and_full_gate(self):
        workflow_path = ROOT / ".github/workflows/test.yml"
        self.assertTrue(workflow_path.is_file(), "CI workflow must exist")
        workflow = workflow_path.read_text(encoding="utf-8")

        self.assertRegex(
            workflow,
            r"(?ms)^on:\s*\n\s+pull_request:\s*\n\s+push:\s*\n"
            r"\s+branches:\s*\[\s*main\s*,\s*develop\s*]",
        )
        self.assertRegex(
            workflow,
            r'python-version:\s*\[\s*["\']3\.8["\']\s*,\s*["\']3\.12["\']\s*]',
        )
        self.assertIn("python-version: ${{ matrix.python-version }}", workflow)

        run_commands = re.findall(r"(?m)^\s*-?\s*run:\s*(\S.*)$", workflow)
        self.assertEqual(
            [
                "python3 -m unittest discover -s tests -p 'test_*.py'",
                "bash tests/test_hooks_shell.sh",
                "bash tests/test_install_shell.sh",
                "bash -n install.sh hooks-handlers/session-start.sh hooks-handlers/prompt-submit.sh",
            ],
            run_commands,
        )

    def test_plugin_marketplace_and_project_versions_match(self):
        plugin = json.loads(
            (ROOT / ".claude-plugin/plugin.json").read_text(encoding="utf-8")
        )
        marketplace = json.loads(
            (ROOT / ".claude-plugin/marketplace.json").read_text(encoding="utf-8")
        )
        account_entries = [
            entry for entry in marketplace["plugins"] if entry.get("name") == "account"
        ]
        self.assertEqual(1, len(account_entries), "marketplace must contain one account entry")

        versions = {
            "plugin.json": plugin["version"],
            "marketplace.json": account_entries[0]["version"],
            "pyproject.toml": read_project_version(),
        }
        self.assertEqual(
            1,
            len(set(versions.values())),
            "release metadata versions differ: "
            + ", ".join("{}={}".format(name, value) for name, value in versions.items()),
        )

    def test_install_reads_plugin_version_without_literal(self):
        install = (ROOT / "install.sh").read_text(encoding="utf-8")
        literal_assignment = re.compile(
            r"(?m)^\s*PLUGIN_VERSION\s*=\s*[\"']?\d+\.\d+\.\d+[\"']?\s*(?:#.*)?$"
        )
        self.assertIsNone(
            literal_assignment.search(install),
            "install.sh must not hard-code PLUGIN_VERSION",
        )
        assignment = next(
            (
                line
                for line in install.splitlines()
                if line.strip().startswith("PLUGIN_VERSION=")
            ),
            "",
        )
        self.assertIn(".claude-plugin/plugin.json", assignment)
        self.assertRegex(assignment, r"json\.(?:load|loads)")
        self.assertIn('["version"]', assignment)

    def test_release_skill_orders_version_gate_and_publication(self):
        release = read_release_skill()
        required_in_order = [
            "git fetch origin '{}'".format(DEVELOP_REFSPEC),
            "git checkout develop",
            DEVELOP_CREATE_COMMAND,
            "git merge --ff-only origin/develop",
            'test "$(git rev-parse HEAD)" = "$(git rev-parse origin/develop)"',
            'test -z "$(git status --porcelain)"',
            "remote tag",
            "local cache",
            ".claude-plugin/plugin.json",
            ".claude-plugin/marketplace.json",
            "pyproject.toml",
            "CHANGELOG.md",
            "--base-ref",
            '"$PYTHON38" -m unittest discover -s tests -p \'test_*.py\'',
            '"$PYTHON38" -m unittest discover -s prototype/switchboard-menubar/tests -p \'test_*.py\'',
            "bash tests/test_hooks_shell.sh",
            "bash tests/test_install_shell.sh",
            "prototype/switchboard-menubar/run.sh --build-only",
            "codesign --verify --deep --strict",
            "git add .claude-plugin/plugin.json .claude-plugin/marketplace.json pyproject.toml CHANGELOG.md README.md README.ko.md",
            "git commit",
            "git push origin develop",
            "git fetch origin '{}'".format(DEVELOP_REFSPEC),
            'test "$(git rev-parse origin/develop)" = "$RELEASE_SHA"',
            "git fetch origin '{}'".format(MAIN_REFSPEC),
            "git checkout main",
            "git merge --ff-only origin/main",
            'test "$(git rev-parse HEAD)" = "$(git rev-parse origin/main)"',
            'git merge --no-ff "$RELEASE_SHA" -m "Merge develop: v{version}"',
            "main HEAD",
            "git tag -a",
            "git push origin main",
            "git fetch origin '{}'".format(MAIN_REFSPEC),
            'test "$(git rev-parse origin/main)" = "$MAIN_SHA"',
            "git push origin v{version}",
            "marketplace clone",
            "git -C \"$HOME/.claude/plugins/marketplaces/lee-ji-hoon\" fetch origin '{}'".format(
                MAIN_REFSPEC
            ),
            "$HOME/.claude/plugins/cache/lee-ji-hoon/account/{version}",
        ]

        position = -1
        for marker in required_in_order:
            next_position = release.find(marker, position + 1)
            self.assertNotEqual(
                -1,
                next_position,
                "release skill is missing or misorders {!r}".format(marker),
            )
            position = next_position

    def test_release_skill_wraps_every_bash_gate_in_fail_fast_execution(self):
        blocks = release_bash_blocks(read_release_skill())
        self.assertGreaterEqual(len(blocks), 6, "release skill must expose every gate")

        for index, block in enumerate(blocks, start=1):
            lines = block.splitlines()
            self.assertEqual(
                "bash -euo pipefail <<'SH'",
                lines[0],
                "release bash block {} must enter fail-fast bash".format(index),
            )
            self.assertEqual(
                "SH",
                lines[-1],
                "release bash block {} must close the fail-fast unit".format(index),
            )

    def test_release_skill_rejects_local_ahead_develop_and_main(self):
        release = read_release_skill()
        develop_block = block_containing(release, "git checkout develop")
        main_block = block_containing(release, "git checkout main")

        assert_markers_in_order(
            self,
            develop_block,
            [
                "git fetch origin '{}'".format(DEVELOP_REFSPEC),
                "git checkout develop",
                DEVELOP_CREATE_COMMAND,
                "git merge --ff-only origin/develop",
                'test "$(git rev-parse HEAD)" = "$(git rev-parse origin/develop)"',
                'test -z "$(git status --porcelain)"',
            ],
        )
        assert_markers_in_order(
            self,
            main_block,
            [
                "git fetch origin '{}'".format(MAIN_REFSPEC),
                "git checkout main",
                "git merge --ff-only origin/main",
                'test "$(git rev-parse HEAD)" = "$(git rev-parse origin/main)"',
                'git merge --no-ff "$RELEASE_SHA" -m "Merge develop: v{version}"',
            ],
        )

    def test_release_skill_supports_single_branch_fetch_configuration(self):
        release = read_release_skill()
        develop_block = block_containing(release, "git checkout develop")
        publication = block_containing(release, 'git commit -m "release: v{version}"')
        marketplace = block_containing(
            release,
            'git -C "$HOME/.claude/plugins/marketplaces/lee-ji-hoon" checkout main',
        )

        self.assertNotIn("git pull", develop_block)
        self.assertNotIn("git pull", publication)
        self.assertNotIn("git pull", marketplace)
        self.assertNotIn("git checkout -b develop --track origin/develop", develop_block)
        self.assertNotIn("git config branch.develop.", develop_block)
        self.assertNotIn("git config --add remote.origin.fetch", develop_block)
        self.assertNotIn("\ngit fetch origin develop\n", release)
        self.assertNotIn("\ngit fetch origin main\n", release)
        assert_markers_in_order(
            self,
            develop_block,
            [
                "git fetch origin '{}'".format(DEVELOP_REFSPEC),
                "if git show-ref --verify --quiet refs/heads/develop; then",
                "git checkout develop",
                DEVELOP_CREATE_COMMAND,
                "git merge --ff-only origin/develop",
                'test "$(git rev-parse HEAD)" = "$(git rev-parse origin/develop)"',
                'test -z "$(git status --porcelain)"',
            ],
        )
        assert_markers_in_order(
            self,
            publication,
            [
                "git push origin develop",
                "git fetch origin '{}'".format(DEVELOP_REFSPEC),
                'test "$(git rev-parse origin/develop)" = "$RELEASE_SHA"',
                "git fetch origin '{}'".format(MAIN_REFSPEC),
                "git checkout main",
                "git merge --ff-only origin/main",
                'test "$(git rev-parse HEAD)" = "$(git rev-parse origin/main)"',
                'git merge --no-ff "$RELEASE_SHA" -m "Merge develop: v{version}"',
                'test "$(git rev-parse "$MAIN_SHA^2")" = "$RELEASE_SHA"',
            ],
        )
        assert_markers_in_order(
            self,
            marketplace,
            [
                MARKETPLACE_CLEAN_GUARD,
                "git -C \"$HOME/.claude/plugins/marketplaces/lee-ji-hoon\" fetch origin '{}'".format(
                    MAIN_REFSPEC
                ),
                'git -C "$HOME/.claude/plugins/marketplaces/lee-ji-hoon" checkout main',
                'git -C "$HOME/.claude/plugins/marketplaces/lee-ji-hoon" merge --ff-only origin/main',
                MARKETPLACE_EQUALITY_GUARD,
                MARKETPLACE_CLEAN_GUARD,
            ],
        )

    def test_marketplace_cache_block_rejects_dirty_checkout_before_fetch(self):
        marketplace = block_containing(
            read_release_skill(),
            'git -C "$HOME/.claude/plugins/marketplaces/lee-ji-hoon" checkout main',
        )
        with tempfile.TemporaryDirectory() as tmp:
            _, seed, home, clone = create_single_branch_marketplace_fixture(Path(tmp))
            initial_sha = run_git("-C", str(clone), "rev-parse", "HEAD").stdout.strip()
            run_git("-C", str(seed), "commit", "-q", "--allow-empty", "-m", "remote")
            run_git("-C", str(seed), "push", "-q", "origin", "main")
            (clone / "dirty.txt").write_text("dirty\n", encoding="utf-8")

            result = run_release_block(marketplace, home)

            self.assertNotEqual(0, result.returncode)
            self.assertEqual(
                initial_sha,
                run_git("-C", str(clone), "rev-parse", "HEAD").stdout.strip(),
                "dirty checkout must fail before merge mutation",
            )
            self.assertEqual(
                initial_sha,
                run_git("-C", str(clone), "rev-parse", "origin/main").stdout.strip(),
                "dirty checkout must fail before fetch mutation",
            )

    def test_marketplace_cache_block_rejects_local_main_ahead(self):
        marketplace = block_containing(
            read_release_skill(),
            'git -C "$HOME/.claude/plugins/marketplaces/lee-ji-hoon" checkout main',
        )
        with tempfile.TemporaryDirectory() as tmp:
            _, _, home, clone = create_single_branch_marketplace_fixture(Path(tmp))
            run_git("-C", str(clone), "config", "user.name", "test")
            run_git("-C", str(clone), "config", "user.email", "test@example.invalid")
            run_git("-C", str(clone), "commit", "-q", "--allow-empty", "-m", "local-ahead")

            result = run_release_block(marketplace, home)

            self.assertNotEqual(
                0,
                result.returncode,
                "clean local-ahead main must fail exact remote equality",
            )

    def test_skill_develop_refspec_materializes_tracking_ref_in_single_branch_clone(self):
        release = read_release_skill()
        with tempfile.TemporaryDirectory() as tmp:
            clone, _, develop_sha = create_trackless_develop_fixture(Path(tmp))

            fetch_config = run_git(
                "-C", str(clone), "config", "--get-all", "remote.origin.fetch"
            ).stdout.splitlines()
            self.assertEqual([MAIN_REFSPEC], fetch_config)

            run_git("-C", str(clone), "fetch", "-q", "origin", "develop")
            plain_ref = run_git(
                "-C",
                str(clone),
                "show-ref",
                "--verify",
                "--quiet",
                "refs/remotes/origin/develop",
                check=False,
            )
            self.assertNotEqual(
                0,
                plain_ref.returncode,
                "source-only fetch must reproduce the missing tracking ref",
            )

            refspec_match = re.search(re.escape(DEVELOP_REFSPEC), release)
            self.assertIsNotNone(
                refspec_match,
                "release skill must carry the destination refspec used by this fixture",
            )
            skill_refspec = refspec_match.group(0)
            run_git("-C", str(clone), "fetch", "-q", "origin", skill_refspec)
            tracked = run_git(
                "-C",
                str(clone),
                "show-ref",
                "--verify",
                "--quiet",
                "refs/remotes/origin/develop",
                check=False,
            )
            self.assertEqual(0, tracked.returncode)
            self.assertEqual(
                develop_sha,
                run_git(
                    "-C", str(clone), "rev-parse", "refs/remotes/origin/develop"
                ).stdout.strip(),
            )

    def test_track_option_partially_mutates_trackless_single_branch_clone(self):
        with tempfile.TemporaryDirectory() as tmp:
            clone, main_sha, develop_sha = create_trackless_develop_fixture(Path(tmp))
            run_git("-C", str(clone), "fetch", "-q", "origin", DEVELOP_REFSPEC)

            result = run_git(
                "-C",
                str(clone),
                "checkout",
                "-b",
                "develop",
                "--track",
                "origin/develop",
                check=False,
            )

            self.assertNotEqual(0, result.returncode)
            self.assertIn("starting point 'origin/develop' is not a branch", result.stderr)
            self.assertEqual(
                "main",
                run_git("-C", str(clone), "branch", "--show-current").stdout.strip(),
            )
            self.assertEqual(
                main_sha,
                run_git("-C", str(clone), "rev-parse", "HEAD").stdout.strip(),
            )
            self.assertEqual(
                run_git(
                    "-C", str(clone), "rev-parse", "{}^{{tree}}".format(develop_sha)
                ).stdout.strip(),
                run_git("-C", str(clone), "write-tree").stdout.strip(),
                "failed --track checkout can leave the index at the develop tree",
            )
            self.assertEqual(
                "develop\n",
                (clone / "tree.txt").read_text(encoding="utf-8"),
                "failed --track checkout can leave the worktree at the develop tree",
            )
            self.assertNotEqual(
                "",
                run_git("-C", str(clone), "status", "--porcelain").stdout.strip(),
                "failed --track checkout can leave staged or worktree changes",
            )

    def test_release_skill_creates_trackless_develop_branch_without_partial_failure(self):
        develop_block = block_containing(read_release_skill(), "git checkout develop")
        with tempfile.TemporaryDirectory() as tmp:
            clone, main_sha, develop_sha = create_trackless_develop_fixture(Path(tmp))

            result = run_release_block(develop_block, cwd=clone)

            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual(
                [MAIN_REFSPEC],
                run_git(
                    "-C", str(clone), "config", "--get-all", "remote.origin.fetch"
                ).stdout.splitlines(),
                "develop creation must not depend on widening remote fetch config",
            )
            self.assertEqual(
                "develop",
                run_git("-C", str(clone), "branch", "--show-current").stdout.strip(),
            )
            self.assertEqual(
                develop_sha,
                run_git("-C", str(clone), "rev-parse", "HEAD").stdout.strip(),
            )
            self.assertEqual(
                develop_sha,
                run_git("-C", str(clone), "rev-parse", "origin/develop").stdout.strip(),
            )
            self.assertEqual(
                "",
                run_git("-C", str(clone), "status", "--porcelain").stdout.strip(),
            )
            upstream = run_git(
                "-C",
                str(clone),
                "rev-parse",
                "--abbrev-ref",
                "--symbolic-full-name",
                "@{upstream}",
                check=False,
            )
            self.assertNotEqual(
                0,
                upstream.returncode,
                "trackless develop intentionally has no implicit upstream authority",
            )
            for key in ("branch.develop.remote", "branch.develop.merge"):
                configured = run_git(
                    "-C", str(clone), "config", "--get", key, check=False
                )
                self.assertNotEqual(
                    0,
                    configured.returncode,
                    "release must not create implicit upstream config for {}".format(key),
                )
            self.assertEqual(
                main_sha,
                run_git("-C", str(clone), "rev-parse", "refs/heads/main").stdout.strip(),
                "creating develop must not move the original main branch",
            )
            self.assertEqual(
                "main\n",
                run_git("-C", str(clone), "show", "refs/heads/main:tree.txt").stdout,
                "creating develop must not rewrite the original main tree",
            )

    def test_release_skill_verifies_exact_release_sha_before_each_publication(self):
        publication = block_containing(read_release_skill(), 'git commit -m "release: v{version}"')
        self.assertNotIn(
            "git merge develop",
            publication,
            "main must merge the recorded release commit, not a moving branch name",
        )
        self.assertNotIn(
            '\ngit merge "$RELEASE_SHA"\n',
            publication,
            "main must not fast-forward across the release boundary",
        )

        assert_markers_in_order(
            self,
            publication,
            [
                'git commit -m "release: v{version}"',
                'RELEASE_SHA="$(git rev-parse HEAD)"',
                "git push origin develop",
                "git fetch origin '{}'".format(DEVELOP_REFSPEC),
                'test "$(git rev-parse origin/develop)" = "$RELEASE_SHA"',
                "git fetch origin '{}'".format(MAIN_REFSPEC),
                "git checkout main",
                "git merge --ff-only origin/main",
                'git merge --no-ff "$RELEASE_SHA" -m "Merge develop: v{version}"',
                'MAIN_SHA="$(git rev-parse HEAD)"',
                'test "$MAIN_SHA" != "$RELEASE_SHA"',
                'test "$(git rev-parse "$MAIN_SHA^2")" = "$RELEASE_SHA"',
                'git merge-base --is-ancestor "$RELEASE_SHA" "$MAIN_SHA"',
                'git tag -a v{version} -m "v{version}" "$MAIN_SHA"',
                'TAG_SHA="$(git rev-list -n 1 v{version})"',
                'test "$TAG_SHA" = "$MAIN_SHA"',
                'git merge-base --is-ancestor "$RELEASE_SHA" "$TAG_SHA"',
                "git push origin main",
                "git fetch origin '{}'".format(MAIN_REFSPEC),
                'test "$(git rev-parse origin/main)" = "$MAIN_SHA"',
                "git push origin v{version}",
                'REMOTE_TAG_SHA="$(git ls-remote --tags origin "refs/tags/v{version}^{}"',
                'test "$REMOTE_TAG_SHA" = "$MAIN_SHA"',
                'git merge-base --is-ancestor "$RELEASE_SHA" "$REMOTE_TAG_SHA"',
            ],
        )

    def test_release_skill_commits_the_same_clean_develop_tree_that_passed_gates(self):
        release = read_release_skill()
        gate_end_marker = (
            "bash -n install.sh hooks-handlers/session-start.sh "
            "hooks-handlers/prompt-submit.sh"
        )
        stage_command = (
            "git add .claude-plugin/plugin.json .claude-plugin/marketplace.json "
            "pyproject.toml CHANGELOG.md README.md README.ko.md"
        )
        clean_command = (
            'test -z "$(git status --porcelain)" || { echo '
            '"ERROR: develop worktree is not clean" >&2; exit 1; }'
        )

        self.assertIn(clean_command, release, "release must assert a clean develop tree")

        checkout_position = release.index("git checkout develop")
        merge_position = release.find(
            "git merge --ff-only origin/develop", checkout_position
        )
        self.assertNotEqual(
            -1,
            merge_position,
            "develop must be fast-forwarded from the fetched tracking ref",
        )
        clean_position = release.index(clean_command, merge_position)
        metadata_position = release.index(".claude-plugin/plugin.json", clean_position)
        gate_end = release.index(gate_end_marker, metadata_position) + len(
            gate_end_marker
        )
        commit_position = release.index('git commit -m "release: v{version}"', gate_end)

        git_commands_after_gate = re.findall(
            r"(?m)^git \S.*$", release[gate_end:commit_position]
        )
        self.assertEqual(
            [stage_command],
            git_commands_after_gate,
            "only the four-file staging command may occur between gates and commit",
        )

    def test_release_skill_fails_closed_when_remote_tag_fetch_fails(self):
        release = (ROOT / "skills/release/SKILL.md").read_text(encoding="utf-8")
        fetch_commands = re.findall(
            r"(?m)^git fetch --tags origin.*$",
            release,
        )
        self.assertEqual(
            [
                'git fetch --tags origin || { echo "ERROR: failed to fetch remote tags" '
                ">&2; exit 1; }"
            ],
            fetch_commands,
        )
        self.assertLess(
            release.index(fetch_commands[0]),
            release.index('python3 - "{version}"'),
        )


if __name__ == "__main__":
    unittest.main()
