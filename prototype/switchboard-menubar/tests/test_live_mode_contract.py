import unittest
from pathlib import Path


SOURCE = Path(__file__).resolve().parents[1] / "Sources/main.swift"


class LiveModeContractTest(unittest.TestCase):
    def test_live_merge_does_not_append_demo_accounts(self):
        source = SOURCE.read_text()
        merge_body = source.split("private func merge(snapshot: LiveSnapshot)", 1)[1].split(
            "func provider(_ id: ProviderID)", 1
        )[0]

        self.assertNotIn("Self.samples", merge_body)
        self.assertNotIn("mock@switchboard.demo", merge_body)
        self.assertIn("Self.unavailableProvider", merge_body)
        self.assertIn(r".filter(\.isLiveOrigin)", merge_body)
        self.assertIn(".map { $0.account }", merge_body)

    def test_non_live_snapshot_accounts_are_filtered_before_account_conversion(self):
        source = SOURCE.read_text()

        self.assertIn("var isLiveOrigin: Bool", source)
        self.assertIn('origin == "live"', source)
        self.assertIn('origin: origin == "live" ? .live : .demo,', source)

    def test_demo_only_refresh_returns_before_snapshot_helper_lookup(self):
        source = SOURCE.read_text()
        refresh_body = source.split("func refreshLiveData()", 1)[1].split(
            "private func apply(snapshot", 1
        )[0]

        self.assertIn("guard !demoOnly else { return }", refresh_body)


if __name__ == "__main__":
    unittest.main()
