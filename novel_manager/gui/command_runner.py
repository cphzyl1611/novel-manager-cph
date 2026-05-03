from __future__ import annotations

import sys
from pathlib import Path
from typing import Iterable

try:  # pragma: no cover - exercised only when PySide6 is installed.
    from PySide6.QtCore import QObject, QProcess, Signal
except ImportError:  # pragma: no cover
    QObject = object  # type: ignore[assignment]
    QProcess = None  # type: ignore[assignment]

    class Signal:  # type: ignore[no-redef]
        def __init__(self, *args, **kwargs):
            pass

        def emit(self, *args, **kwargs):
            pass


DRY_RUN_ONLY_COMMANDS = {"apply-renames", "apply-updates", "stage-duplicates", "refresh-metadata", "auto-tag"}

SAFE_ACTIONS = {
    "apply_selected_renames": ("apply-renames", {"--confirm", "--yes-i-understand"}),
    "apply_recommended_updates": ("apply-updates", {"--confirm", "--yes-i-understand"}),
    "move_single_book_to_trash": ("move-to-trash", {"--confirm", "--yes-i-understand"}),
    "apply_auto_tags": ("auto-tag", {"--apply"}),
    "refresh_metadata": ("refresh-metadata", {"--apply"}),
}


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def build_cli_command(python_executable: str, command: str, repo: str | Path, extra_args: Iterable[str] | None = None) -> list[str]:
    args = [python_executable, str(project_root() / "run.py"), command, "--repo", str(repo)]
    args.extend(str(item) for item in (extra_args or []))
    return args


def is_confirm_command(cmd_args: Iterable[str]) -> bool:
    args = set(str(item) for item in cmd_args)
    return "--confirm" in args or "--yes-i-understand" in args


def is_dangerous_command(command: str, extra_args: Iterable[str] | None = None) -> bool:
    args = set(str(item) for item in (extra_args or []))
    if is_confirm_command(args):
        return True
    if command in DRY_RUN_ONLY_COMMANDS and "--dry-run" not in args:
        return True
    if command in {"group-books", "find-duplicates"} and "--apply" in args:
        return True
    if command == "move-to-trash" and "--dry-run" not in args:
        return True
    return False


def _has_required_args(args: set[str], required: set[str]) -> bool:
    return required <= args


def ensure_gui_safe_command(command: str, extra_args: Iterable[str] | None = None, *, safe_action: str | None = None) -> tuple[bool, str]:
    args = set(str(item) for item in (extra_args or []))
    if safe_action:
        allowed = SAFE_ACTIONS.get(safe_action)
        if not allowed:
            return False, "未知的安全操作，已阻止执行。"
        allowed_command, required = allowed
        if command != allowed_command or not _has_required_args(args, required):
            return False, "安全操作与命令不匹配，已阻止执行。"
        if command == "move-to-trash" and "--book-id" not in args:
            return False, "移入废弃区必须指定单本小说。"
        return True, ""
    if command == "move-to-trash":
        if "--dry-run" in args and not is_confirm_command(args):
            return True, ""
        return False, "GUI 只允许预览移入废弃区，不执行真实移动。"
    if is_confirm_command(args):
        return False, "GUI 不允许执行确认操作，只能预览。"
    if command in DRY_RUN_ONLY_COMMANDS:
        if "--dry-run" not in args:
            return False, f"GUI 只支持预览操作：{command} 必须带 --dry-run。"
        if "--apply" in args:
            return False, f"GUI 只支持预览操作：{command} 不允许 --apply。"
    if command == "group-books" and "--apply" in args:
        return False, "GUI 不允许 group-books --apply。"
    if command == "find-duplicates" and "--apply" in args:
        return False, "GUI 不允许 find-duplicates --apply。"
    return True, ""


def is_command_allowed_in_gui(command: str, extra_args: Iterable[str] | None = None, *, safe_action: str | None = None) -> tuple[bool, str]:
    return ensure_gui_safe_command(command, extra_args, safe_action=safe_action)


class CommandRunner(QObject):  # pragma: no cover - GUI integration
    output = Signal(str)
    started = Signal(str)
    finished = Signal(int)
    state_changed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.process = None

    def is_running(self) -> bool:
        return self.process is not None and self.process.state() != QProcess.NotRunning

    def run(self, command: list[str]) -> bool:
        if QProcess is None:
            self.output.emit("未安装 PySide6。请先运行：pip install -r requirements.txt")
            return False
        if self.is_running():
            self.output.emit("已有任务正在运行，请等待结束或先停止任务。")
            return False
        program, args = command[0], command[1:]
        self.process = QProcess(self)
        self.process.setProgram(program)
        self.process.setArguments(args)
        self.process.setWorkingDirectory(str(project_root()))
        self.process.readyReadStandardOutput.connect(self._read_stdout)
        self.process.readyReadStandardError.connect(self._read_stderr)
        self.process.finished.connect(self._finished)
        display = " ".join(command)
        self.started.emit(display)
        self.state_changed.emit("running")
        self.process.start()
        return True

    def stop(self) -> None:
        if self.is_running():
            self.output.emit("正在停止任务...")
            self.process.terminate()
            if not self.process.waitForFinished(3000):
                self.process.kill()

    def _read_stdout(self) -> None:
        data = bytes(self.process.readAllStandardOutput()).decode("utf-8", errors="replace")
        if data:
            self.output.emit(data)

    def _read_stderr(self) -> None:
        data = bytes(self.process.readAllStandardError()).decode("utf-8", errors="replace")
        if data:
            self.output.emit(data)

    def _finished(self, code: int, _status) -> None:
        self.output.emit(f"\n[任务结束：{code}]\n")
        self.state_changed.emit("idle")
        self.finished.emit(code)


def default_python() -> str:
    return sys.executable or "python"
