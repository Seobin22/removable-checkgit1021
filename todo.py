"""터미널용 할 일 관리 CLI.

사용법:
  py todo.py add "내용" [--due YYYY-MM-DD]
  py todo.py list
  py todo.py done <번호>
  py todo.py delete <번호>

데이터는 한 줄에 하나씩 UTF-8로 저장한다. 예:
  [ ] 우유 사기 | 마감: 2026-10-25
  [x] 보고서 제출
저장 파일은 기본값이 이 스크립트 옆의 빈파일.txt이고, 환경변수 TODO_FILE로 바꿀 수 있다.
"""
import os
import sys
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

DEFAULT_FILE = Path(__file__).with_name("빈파일.txt")
DUE_SEPARATOR = " | 마감: "
USAGE = """사용법:
  py todo.py add "내용" [--due YYYY-MM-DD]   할 일 추가
  py todo.py list                           목록 보기
  py todo.py done <번호>                     완료 표시
  py todo.py delete <번호>                   삭제"""


class TodoError(Exception):
    """사용자에게 그대로 보여줄 오류."""


@dataclass
class Todo:
    text: str
    done: bool = False
    due: date | None = None

    def to_line(self):
        line = f"[{'x' if self.done else ' '}] {self.text}"
        if self.due:
            line += f"{DUE_SEPARATOR}{self.due.isoformat()}"
        return line

    @classmethod
    def from_line(cls, line):
        done = line.startswith("[x]")
        body = line[4:]
        due = None
        if DUE_SEPARATOR in body:
            body, due_text = body.rsplit(DUE_SEPARATOR, 1)
            due = date.fromisoformat(due_text.strip())
        return cls(text=body, done=done, due=due)

    def is_overdue(self, today):
        return not self.done and self.due is not None and self.due < today


def data_path():
    return Path(os.environ.get("TODO_FILE") or DEFAULT_FILE)


def load():
    path = data_path()
    if not path.exists():
        return []
    todos = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        if not line.strip():
            continue
        try:
            todos.append(Todo.from_line(line))
        except ValueError:
            raise TodoError(
                f"{path.name} {line_no}번째 줄의 마감일을 읽을 수 없습니다: '{line}'\n"
                "파일을 열어 날짜를 YYYY-MM-DD 형식의 실제 날짜로 고쳐 주세요."
            )
    return todos


def save(todos):
    content = "".join(todo.to_line() + "\n" for todo in todos)
    data_path().write_text(content, encoding="utf-8")


def parse_date(text):
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        raise TodoError(
            f"날짜 형식이 올바르지 않습니다: '{text}' "
            "(YYYY-MM-DD 형식의 실제 날짜로 입력하세요. 예: 2026-10-25)"
        )


def parse_index(text, todos):
    try:
        number = int(text)
    except ValueError:
        raise TodoError(f"번호는 숫자여야 합니다: '{text}'")
    if not 1 <= number <= len(todos):
        if todos:
            hint = f"1~{len(todos)}번 중에서 고르세요"
        else:
            hint = "아직 할 일이 없습니다"
        raise TodoError(f"{number}번 할 일이 없습니다. ({hint})")
    return number - 1


def cmd_add(args):
    due = None
    if "--due" in args:
        pos = args.index("--due")
        if pos + 1 >= len(args):
            raise TodoError("--due 뒤에 날짜를 입력하세요. (YYYY-MM-DD 형식, 예: 2026-10-25)")
        due = parse_date(args[pos + 1])
        args = args[:pos] + args[pos + 2:]
    text = " ".join(args).strip()
    if not text:
        raise TodoError('할 일 내용을 입력하세요. 예: py todo.py add "우유 사기"')

    todos = load()
    todo = Todo(text=text, due=due)
    todos.append(todo)
    save(todos)
    print(f"추가됨: {len(todos)}. {format_todo(todo)}")


def cmd_list(args):
    todos = load()
    if not todos:
        print("할 일이 없습니다.")
        return
    today = date.today()
    for number, todo in enumerate(todos, 1):
        line = f"{number}. [{'x' if todo.done else ' '}] {format_todo(todo)}"
        if todo.is_overdue(today):
            line += "  ※ 기한 지남"
        print(line)


def cmd_done(args):
    todos = load()
    index = parse_index(require_number(args), todos)
    todo = todos[index]
    if todo.done:
        print(f"이미 완료된 항목입니다: {index + 1}. {todo.text}")
        return
    todo.done = True
    save(todos)
    print(f"완료: {index + 1}. {todo.text}")


def cmd_delete(args):
    todos = load()
    index = parse_index(require_number(args), todos)
    todo = todos.pop(index)
    save(todos)
    print(f"삭제됨: {index + 1}. {todo.text}")


def require_number(args):
    if not args:
        raise TodoError("번호를 입력하세요. 번호는 'py todo.py list'로 확인할 수 있습니다.")
    return args[0]


def format_todo(todo):
    if todo.due:
        return f"{todo.text} (마감: {todo.due.isoformat()})"
    return todo.text


COMMANDS = {"add": cmd_add, "list": cmd_list, "done": cmd_done, "delete": cmd_delete}


def output_encoding(console_cp):
    """파이프 출력에 쓸 인코딩. 받는 쪽(PowerShell 등)은 콘솔 코드페이지로 해석한다."""
    return f"cp{console_cp}" if console_cp else "utf-8"


def console_code_page():
    try:
        import ctypes
        return ctypes.windll.kernel32.GetConsoleOutputCP()
    except (AttributeError, OSError):
        return 0  # Windows가 아니거나 연결된 콘솔이 없음


def main(argv):
    # 화면에 바로 출력할 때는 Python이 유니코드 콘솔 API를 써서 한글이 깨지지 않는다.
    # 파이프(변수 저장, | 연결)일 때만 부모 콘솔의 코드페이지(cp949, UTF-8 등)에 맞춘다.
    for stream in (sys.stdout, sys.stderr):
        if not stream.isatty():
            stream.reconfigure(encoding=output_encoding(console_code_page()), errors="replace")

    if not argv:
        print(USAGE, file=sys.stderr)
        return 1
    command, args = argv[0], argv[1:]
    if command not in COMMANDS:
        print(f"오류: 알 수 없는 명령입니다: '{command}'\n\n{USAGE}", file=sys.stderr)
        return 1
    try:
        COMMANDS[command](args)
    except TodoError as error:
        print(f"오류: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
