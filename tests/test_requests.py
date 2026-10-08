import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import cancel_pending_requests as app


class RequestTests(unittest.TestCase):
    def test_html_unicode_deduplication_and_nested_text(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "input.html"
            path.write_text("<table><tr><td>Kullan\u0131c\u0131 ad\u0131</td><td><b>Demo.One</b></td></tr>"
                            "<tr><td>Username</td><td>demo.one</td></tr>"
                            "<tr><td>Username</td><td>demo_two</td></tr></table>", encoding="utf-8-sig")
            self.assertEqual(app.read_users(path), ["Demo.One", "demo_two"])

    def test_invalid_username_is_rejected(self):
        parser = app.UsernameParser()
        with self.assertRaises(ValueError):
            parser.feed("<tr><td>Username</td><td>../unsafe</td></tr>")

    def test_empty_export_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "empty.html"
            path.write_text("<html></html>", encoding="utf-8")
            with self.assertRaises(ValueError):
                app.read_users(path)

    def test_resume_and_explicit_retry(self):
        state = {"done": {"completed": {}}, "errors": {"failed": {}}}
        users = ["Completed", "Failed", "new"]
        self.assertEqual(app.remaining_users(users, state), ["new"])
        self.assertEqual(app.remaining_users(users, state, True), ["Failed", "new"])

    def test_state_round_trip_and_temporary_cleanup(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "progress.json"
            app.save_state(path, {"done": {"demo": {"result": "cancelled"}}})
            app.save_state(path, {"done": {}})
            self.assertEqual(json.loads(path.read_text()), {"done": {}})
            self.assertFalse(path.with_suffix(".tmp").exists())

    def test_success_clears_previous_error(self):
        with tempfile.TemporaryDirectory() as directory:
            state = {"done": {}, "errors": {"demo": {}}}
            root = Path(directory)
            with patch.object(app, "cancel_one", return_value="cancelled"):
                self.assertTrue(app.process_profile(Mock(), "Demo", state, root / "state.json", root / "errors.jsonl"))
            self.assertEqual(state["done"]["demo"]["result"], "cancelled")
            self.assertNotIn("demo", state["errors"])

    def test_session_stop_is_logged_and_reraised(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = {"done": {}}
            with patch.object(app, "cancel_one", side_effect=app.SessionStopped("challenge")):
                with self.assertRaises(app.SessionStopped):
                    app.process_profile(Mock(), "Demo", state, root / "state.json", root / "errors.jsonl")
            record = json.loads((root / "errors.jsonl").read_text())
            self.assertEqual(record["type"], "SessionStopped")
            self.assertNotIn("demo", state["done"])


if __name__ == "__main__":
    unittest.main()
