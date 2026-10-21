"""todo.py CLI 테스트.

CLI를 실제 프로세스로 실행해서 출력과 저장 파일을 검사한다.
환경변수 TODO_FILE로 임시 파일을 지정하므로 빈파일.txt 실데이터는 건드리지 않는다.
"""
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

TODO_PY = Path(__file__).with_name("todo.py")


class TodoCliTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.data_file = Path(self.tmpdir.name) / "todos.txt"

    def tearDown(self):
        self.tmpdir.cleanup()

    def run_cli(self, *args):
        env = os.environ.copy()
        env["TODO_FILE"] = str(self.data_file)
        # 부모 환경의 인코딩 설정에 기대지 않고 todo.py 스스로 UTF-8을 처리하는지 확인한다.
        env.pop("PYTHONIOENCODING", None)
        env.pop("PYTHONUTF8", None)
        return subprocess.run(
            [sys.executable, str(TODO_PY), *args],
            capture_output=True,
            encoding="utf-8",
            env=env,
        )

    def stored_lines(self):
        return self.data_file.read_text(encoding="utf-8").splitlines()

    # --- 정상 동작 ---

    def test_add_saves_korean_text_as_utf8(self):
        result = self.run_cli("add", "우유 사기")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("우유 사기", result.stdout)
        self.assertEqual(self.stored_lines(), ["[ ] 우유 사기"])

    def test_add_with_due_date(self):
        result = self.run_cli("add", "보고서 제출", "--due", "2030-01-15")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.stored_lines(), ["[ ] 보고서 제출 | 마감: 2030-01-15"])

    def test_list_shows_numbered_items(self):
        self.run_cli("add", "첫 번째")
        self.run_cli("add", "두 번째", "--due", "2030-01-15")
        result = self.run_cli("list")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("1. [ ] 첫 번째", result.stdout)
        self.assertIn("2. [ ] 두 번째 (마감: 2030-01-15)", result.stdout)

    def test_list_when_empty(self):
        result = self.run_cli("list")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("할 일이 없습니다", result.stdout)

    def test_list_marks_overdue_items(self):
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        today = date.today().isoformat()
        self.run_cli("add", "지난 일", "--due", yesterday)
        self.run_cli("add", "오늘 일", "--due", today)
        lines = self.run_cli("list").stdout.splitlines()
        self.assertIn("기한 지남", lines[0])
        self.assertNotIn("기한 지남", lines[1])

    def test_done_item_is_not_marked_overdue(self):
        self.run_cli("add", "끝난 일", "--due", "2000-01-01")
        self.run_cli("done", "1")
        result = self.run_cli("list")
        self.assertIn("1. [x] 끝난 일", result.stdout)
        self.assertNotIn("기한 지남", result.stdout)

    def test_done_marks_item_complete(self):
        self.run_cli("add", "할 일 A")
        self.run_cli("add", "할 일 B")
        result = self.run_cli("done", "2")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.stored_lines(), ["[ ] 할 일 A", "[x] 할 일 B"])

    def test_done_twice_is_friendly(self):
        self.run_cli("add", "할 일")
        self.run_cli("done", "1")
        result = self.run_cli("done", "1")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("이미 완료", result.stdout)

    def test_delete_removes_item_and_renumbers(self):
        self.run_cli("add", "하나")
        self.run_cli("add", "둘")
        self.run_cli("add", "셋")
        result = self.run_cli("delete", "2")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.stored_lines(), ["[ ] 하나", "[ ] 셋"])
        self.assertIn("2. [ ] 셋", self.run_cli("list").stdout)

    # --- 오류 처리 ---

    def assert_friendly_error(self, result, *fragments):
        self.assertEqual(result.returncode, 1)
        self.assertNotIn("Traceback", result.stderr)
        self.assertIn("오류", result.stderr)
        for fragment in fragments:
            self.assertIn(fragment, result.stderr)

    def test_done_with_missing_number(self):
        self.run_cli("add", "하나")
        self.assert_friendly_error(self.run_cli("done", "5"), "5번")

    def test_delete_with_missing_number(self):
        self.assert_friendly_error(self.run_cli("delete", "1"), "1번")

    def test_number_must_be_numeric(self):
        self.run_cli("add", "하나")
        self.assert_friendly_error(self.run_cli("done", "abc"), "숫자")

    def test_zero_or_negative_number(self):
        self.run_cli("add", "하나")
        self.assert_friendly_error(self.run_cli("done", "0"), "0번")

    def test_invalid_date_format(self):
        result = self.run_cli("add", "할 일", "--due", "10/25")
        self.assert_friendly_error(result, "날짜", "YYYY-MM-DD")
        self.assertFalse(self.data_file.exists() and self.stored_lines())

    def test_impossible_date(self):
        self.assert_friendly_error(self.run_cli("add", "할 일", "--due", "2026-13-40"), "날짜")

    def test_due_without_value(self):
        self.assert_friendly_error(self.run_cli("add", "할 일", "--due"), "날짜")

    def test_empty_content(self):
        self.assert_friendly_error(self.run_cli("add", "   "), "내용")

    def test_unknown_command(self):
        self.assert_friendly_error(self.run_cli("fly"), "fly")

    def test_no_command_shows_usage(self):
        result = self.run_cli()
        self.assertEqual(result.returncode, 1)
        self.assertIn("사용법", result.stderr)


if __name__ == "__main__":
    unittest.main()
