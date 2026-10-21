"""todo.py CLI 테스트.

CLI를 실제 프로세스로 실행해서 출력과 저장 파일을 검사한다.
환경변수 TODO_FILE로 임시 파일을 지정하므로 빈파일.txt 실데이터는 건드리지 않는다.
"""
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import date, timedelta
from io import StringIO
from pathlib import Path
from unittest import mock

import todo

TODO_PY = Path(__file__).with_name("todo.py")
# todo.py는 파이프 출력을 콘솔 코드페이지에 맞추므로, 받는 쪽도 같은 인코딩으로 읽는다.
PIPE_ENCODING = todo.output_encoding(todo.console_code_page())


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
            encoding=PIPE_ENCODING,
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

    # --- archive ---

    def archive_lines(self):
        archive_file = self.data_file.with_name("todos_보관.txt")
        return archive_file.read_text(encoding="utf-8").splitlines()

    def test_archive_moves_done_items_to_separate_file(self):
        self.run_cli("add", "남길 일")
        self.run_cli("add", "끝난 일", "--due", "2026-10-01")
        self.run_cli("add", "또 남길 일")
        self.run_cli("add", "또 끝난 일")
        self.run_cli("done", "2")
        self.run_cli("done", "4")

        result = self.run_cli("archive")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("2개", result.stdout)
        self.assertEqual(self.stored_lines(), ["[ ] 남길 일", "[ ] 또 남길 일"])
        today = date.today().isoformat()
        self.assertEqual(
            self.archive_lines(),
            [
                f"[x] 끝난 일 | 마감: 2026-10-01 | 보관일: {today}",
                f"[x] 또 끝난 일 | 보관일: {today}",
            ],
        )

    def test_archive_renumbers_remaining_items(self):
        self.run_cli("add", "끝난 일")
        self.run_cli("add", "남길 일")
        self.run_cli("done", "1")
        self.run_cli("archive")
        self.assertIn("1. [ ] 남길 일", self.run_cli("list").stdout)

    def test_archive_appends_to_existing_archive(self):
        self.run_cli("add", "첫 번째")
        self.run_cli("done", "1")
        self.run_cli("archive")
        self.run_cli("add", "두 번째")
        self.run_cli("done", "1")
        self.run_cli("archive")
        archived = self.archive_lines()
        self.assertEqual(len(archived), 2)
        self.assertTrue(archived[0].startswith("[x] 첫 번째"))
        self.assertTrue(archived[1].startswith("[x] 두 번째"))

    def test_archive_with_nothing_done(self):
        self.run_cli("add", "아직 안 한 일")
        result = self.run_cli("archive")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("보관할 완료 항목이 없습니다", result.stdout)
        self.assertEqual(self.stored_lines(), ["[ ] 아직 안 한 일"])
        self.assertFalse(self.data_file.with_name("todos_보관.txt").exists())

    def test_usage_mentions_archive(self):
        self.assertIn("archive", self.run_cli().stderr)

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

    def test_hand_edited_file_with_bad_date(self):
        # 사람이 메모장으로 파일을 고치다 날짜를 망가뜨린 경우
        self.data_file.write_text(
            "[ ] 정상 항목\n[ ] 고장난 항목 | 마감: 2026-02-30\n", encoding="utf-8"
        )
        self.assert_friendly_error(self.run_cli("list"), "2번째 줄")

    def test_file_saved_with_bom_by_notepad(self):
        self.data_file.write_text("[ ] 메모장에서 쓴 항목\n", encoding="utf-8-sig")
        result = self.run_cli("list")
        self.assertIn("1. [ ] 메모장에서 쓴 항목", result.stdout)

    def test_no_command_shows_usage(self):
        result = self.run_cli()
        self.assertEqual(result.returncode, 1)
        self.assertIn("사용법", result.stderr)


class OutputEncodingTest(unittest.TestCase):
    """한국어 Windows 기본 PowerShell(cp949)로 출력을 받아도 깨지지 않는지 확인."""

    def test_pipe_encoding_follows_console_code_page(self):
        self.assertEqual(todo.output_encoding(949), "cp949")
        self.assertEqual(todo.output_encoding(65001), "cp65001")
        self.assertEqual(todo.output_encoding(0), "utf-8")

    def test_list_output_is_representable_in_cp949(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_file = Path(tmp) / "todos.txt"
            data_file.write_text("[ ] 장보기: 우유, 계란 | 마감: 2000-01-01\n", encoding="utf-8")
            buffer = StringIO()
            with mock.patch.dict(os.environ, {"TODO_FILE": str(data_file)}), redirect_stdout(buffer):
                todo.cmd_list([])
        output = buffer.getvalue()
        self.assertIn("기한 지남", output)
        # cp949에 없는 문자(예: ⚠)가 있으면 여기서 UnicodeEncodeError가 난다.
        output.encode("cp949")


if __name__ == "__main__":
    unittest.main()
