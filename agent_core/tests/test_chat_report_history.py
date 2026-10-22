"""Exercise UI history save/reload without importing or starting the Maria app."""
import ast
from datetime import datetime
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest


ROOT = Path(__file__).resolve().parents[2]


class ReportHistoryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "chat.jsonl"
        source = ROOT / "maria_ui/app.py"
        tree = ast.parse(source.read_text())
        names = {"save_chat_message", "_load_persisted_chat_history", "get_ui_chat_history"}
        selected = [node for node in tree.body
                    if isinstance(node, ast.FunctionDef) and node.name in names]
        self.assertEqual({node.name for node in selected}, names)
        self.context = {
            "CHAT_LOG_FILE": self.path, "time": time, "datetime": datetime, "json": json,
            "_ui_chat_history": [], "_ui_chat_history_loaded": False,
            "_ui_chat_lock": threading.Lock(), "MAX_UI_CHAT_HISTORY": 50,
            # The storage reader's contract: parsed, bounded, ordered entries.
            "read_jsonl_tail": lambda path, limit: [
                json.loads(line) for line in path.read_text().splitlines()[-limit:]],
        }
        exec(compile(ast.Module(body=selected, type_ignores=[]), str(source), "exec"),
             self.context)

    def test_full_long_report_survives_reload_with_legacy_messages(self):
        legacy = {"timestamp": 1, "role": "maria", "content": "Stary zapis."}
        self.path.write_text(json.dumps(legacy) + "\n")
        report = "## W skrócie\nPięć projektów, bez nowych analiz.\n\n## Pełny raport\n"
        report += "\n".join(f"Projekt {n}: gotowe pliki, następny krok — test." for n in range(100))
        self.assertGreater(len(report), 2000)
        self.context["save_chat_message"]("maria", report)
        result = self.context["get_ui_chat_history"]()
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["content"], legacy["content"])
        self.assertEqual(result[1]["content"], report)
        self.assertFalse(json.loads(self.path.read_text().splitlines()[-1])["truncated"])
        self.assertEqual(self.context["get_ui_chat_history"](), result)

    def test_oversized_report_is_bounded_and_visibly_marked(self):
        self.context["save_chat_message"]("maria", "ą" * 50000)
        saved = json.loads(self.path.read_text())
        self.assertTrue(saved["truncated"])
        self.assertEqual(len(saved["content"]), 40000)
        self.assertIn("[Zapis historii skrócony:", saved["content"])
        self.assertEqual(self.context["get_ui_chat_history"]()[0]["content"], saved["content"])

    def test_quotes_newlines_and_unicode_round_trip(self):
        text = 'Zażółć gęślą jaźń.\n"tekst" </script> \\\\ dane\n' * 20
        self.context["save_chat_message"]("user", text)
        self.assertEqual(len(self.path.read_text().splitlines()), 1)
        self.assertEqual(self.context["get_ui_chat_history"]()[0]["content"], text)


if __name__ == "__main__":
    unittest.main()
