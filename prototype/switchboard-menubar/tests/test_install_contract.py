import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class AppInstallContractTest(unittest.TestCase):
    def test_build_failure_is_not_hidden_by_output_filtering(self):
        source = (ROOT / "install.sh").read_text()
        self.assertIn('APP_SOURCE="$("$SCRIPT_DIR/run.sh" --build-only)"', source)
        self.assertNotIn("tail -n 1", source)

    def test_failed_copy_restores_previous_app(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            script_directory = root / "installer"
            script_directory.mkdir()
            shutil.copy2(ROOT / "install.sh", script_directory / "install.sh")
            source_app = root / "source" / "Switchboard.app"
            source_app.mkdir(parents=True)
            run_script = script_directory / "run.sh"
            run_script.write_text("#!/bin/sh\nprintf '%s\\n' '%s'\n" % ("%s", source_app))
            run_script.chmod(0o755)

            target_app = root / "home" / "Applications" / "Switchboard.app"
            target_app.mkdir(parents=True)
            (target_app / "marker").write_text("previous")
            binary_directory = root / "bin"
            binary_directory.mkdir()
            ditto = binary_directory / "ditto"
            ditto.write_text("#!/bin/sh\nexit 42\n")
            ditto.chmod(0o755)

            environment = os.environ.copy()
            environment["HOME"] = str(root / "home")
            environment["PATH"] = "%s:%s" % (binary_directory, environment["PATH"])
            result = subprocess.run(
                ["bash", str(script_directory / "install.sh")],
                env=environment,
                capture_output=True,
                text=True,
            )

            self.assertEqual(42, result.returncode)
            self.assertEqual("previous", (target_app / "marker").read_text())
            self.assertEqual([], list(target_app.parent.glob("Switchboard.backup-*.app")))
            self.assertIn("기존 앱 복구 완료", result.stderr)

    def test_failed_first_install_removes_partial_app(self):
        source = (ROOT / "install.sh").read_text()
        self.assertIn('if [[ -e "$TARGET_APP" ]]', source)
        self.assertIn('불완전한 앱 제거 완료', source)


if __name__ == "__main__":
    unittest.main()
