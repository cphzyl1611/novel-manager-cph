from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFileDialog, QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMessageBox, QPushButton, QStackedWidget, QStatusBar, QToolBar, QVBoxLayout, QWidget

from .command_runner import CommandRunner, build_cli_command, default_python, is_command_allowed_in_gui
from .i18n import command_label
from .pages.books_page import BooksPage
from .pages.dashboard_page import DashboardPage
from .pages.duplicate_page import DuplicatePage
from .pages.health_page import HealthPage
from .pages.issues_page import IssuesPage
from .pages.logs_page import LogsPage
from .pages.rename_plan_page import RenamePlanPage
from .pages.reports_page import ReportsPage
from .pages.settings_page import SettingsPage
from .pages.tools_page import ToolsPage
from .pages.update_page import UpdatePage
from .pages.welcome_page import WelcomeDialog
from .repo_state import get_repo_structure_status, load_dashboard_stats, load_gui_settings, save_gui_settings


class MainWindow(QMainWindow):  # pragma: no cover
    def __init__(self):
        super().__init__()
        self.setWindowTitle("小说整理助手")
        self.resize(1280, 820)
        self.settings = load_gui_settings()
        self.repo = self.settings.get("last_repo_path", "")
        self.python_path = self.settings.get("python_path", default_python())
        self.runner = CommandRunner(self)
        self.runner.output.connect(self.append_log)
        self.runner.started.connect(self._task_started)
        self.runner.finished.connect(self._task_finished)
        self._build_toolbar()
        self._build_body()
        self._build_statusbar()
        self._load_style()
        self.refresh_all()
        if not self.repo or not Path(self.repo).exists():
            self.show_welcome()

    def _build_toolbar(self) -> None:
        toolbar = QToolBar("Main")
        toolbar.setMovable(False)
        self.addToolBar(Qt.TopToolBarArea, toolbar)
        self.page_title = QLabel("开始整理")
        self.repo_label = QLabel(self.repo or "未选择仓库")
        self.repo_label.setMinimumWidth(360)
        choose = QPushButton("选择仓库")
        choose.clicked.connect(self.choose_repo)
        scan = QPushButton("扫描小说")
        scan.clicked.connect(lambda: self.run_cli("scan", ["--area", "library"]))
        refresh = QPushButton("刷新")
        refresh.clicked.connect(self.refresh_all)
        self.global_search = QLineEdit()
        self.global_search.setPlaceholderText("搜索小说")
        self.global_search.returnPressed.connect(self._global_search)
        for widget in [self.page_title, self.repo_label, choose, scan, refresh, self.global_search]:
            toolbar.addWidget(widget)

    def _build_body(self) -> None:
        central = QWidget()
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        self.nav = QWidget()
        self.nav.setObjectName("Nav")
        nav_layout = QVBoxLayout(self.nav)
        nav_layout.setContentsMargins(8, 12, 8, 12)
        self.stack = QStackedWidget()
        self.dashboard = DashboardPage(self.run_cli, self.switch_page_by_title)
        self.books = BooksPage(self.run_cli)
        self.issues = IssuesPage(self.switch_page_by_title)
        self.duplicates = DuplicatePage(self.run_cli)
        self.updates = UpdatePage(self.run_cli)
        self.rename_plan = RenamePlanPage(self.run_cli)
        self.health = HealthPage(self.run_cli)
        self.reports = ReportsPage(self.run_cli)
        self.tools = ToolsPage(self.run_cli, self.runner.stop)
        self.logs = LogsPage()
        self.settings_page = SettingsPage()
        self.pages: list[tuple[str, QWidget]] = [
            ("开始整理", self.dashboard),
            ("小说库", self.books),
            ("待处理事项", self.issues),
            ("重复与版本", self.duplicates),
            ("更新候选", self.updates),
            ("文件名整理", self.rename_plan),
            ("标签与书单", self.tools),
            ("健康检查", self.health),
            ("历史报告", self.reports),
            ("操作记录", self.logs),
            ("设置", self.settings_page),
        ]
        for title, page in self.pages:
            self.stack.addWidget(page)
            button = QPushButton(title)
            button.setObjectName("NavButton")
            button.clicked.connect(lambda _=False, t=title, p=page: self.switch_page(t, p))
            nav_layout.addWidget(button)
        nav_layout.addStretch()
        layout.addWidget(self.nav)
        layout.addWidget(self.stack, 1)
        self.setCentralWidget(central)

    def _build_statusbar(self) -> None:
        self.status = QStatusBar()
        self.setStatusBar(self.status)
        self.repo_status = QLabel("仓库状态：未选择")
        self.book_count = QLabel("小说数量：0")
        self.last_action = QLabel("最近操作：-")
        self.task_status = QLabel("任务：空闲")
        self.status.addWidget(self.repo_status)
        self.status.addPermanentWidget(self.book_count)
        self.status.addPermanentWidget(self.last_action)
        self.status.addPermanentWidget(self.task_status)

    def _load_style(self) -> None:
        path = Path(__file__).parent / "styles" / "light.qss"
        try:
            self.setStyleSheet(path.read_text(encoding="utf-8"))
        except OSError:
            pass

    def choose_repo(self) -> None:
        selected = QFileDialog.getExistingDirectory(self, "选择小说仓库", self.repo or "")
        if not selected:
            return
        status = get_repo_structure_status(selected)
        if status["kind"] == "plain_txt_folder":
            QMessageBox.warning(self, "这不是小说仓库", "这是普通 TXT 文件夹。请先通过仓库向导导入到小说仓库。")
            return
        self.repo = selected
        self.settings["last_repo_path"] = selected
        save_gui_settings(self.settings)
        self.refresh_all()

    def show_welcome(self) -> None:
        dialog = WelcomeDialog(lambda path: self.run_cli_for_repo("init", path, []), self._set_repo_from_welcome, self)
        dialog.exec()

    def _set_repo_from_welcome(self, path: str) -> None:
        self.repo = path
        self.settings["last_repo_path"] = path
        save_gui_settings(self.settings)
        self.refresh_all()

    def switch_page(self, title: str, page: QWidget) -> None:
        self.page_title.setText(title)
        self.stack.setCurrentWidget(page)
        if hasattr(page, "refresh"):
            page.refresh(self.repo)

    def switch_page_by_title(self, title: str) -> None:
        for page_title, page in self.pages:
            if page_title == title:
                self.switch_page(page_title, page)
                return

    def refresh_all(self) -> None:
        self.repo_label.setText(self.repo or "未选择仓库")
        stats = load_dashboard_stats(self.repo) if self.repo else {"books": 0}
        if self.repo:
            status = get_repo_structure_status(self.repo)
            label = {"initialized_repo": "已初始化", "plain_txt_folder": "普通 TXT 文件夹", "incomplete_or_empty": "目录不完整"}.get(status["kind"], "未知")
        else:
            label = "未选择仓库"
        self.repo_status.setText(f"仓库状态：{label}")
        self.book_count.setText(f"小说数量：{stats.get('books', 0)}")
        for _, page in self.pages:
            if hasattr(page, "refresh"):
                page.refresh(self.repo)

    def _global_search(self) -> None:
        self.switch_page_by_title("小说库")
        self.books.query.setText(self.global_search.text())
        self.books.refresh(self.repo)

    def run_cli(self, command: str, extra_args: list[str] | None = None, *, safe_action: str | None = None) -> None:
        if not self.repo:
            QMessageBox.warning(self, "未选择仓库", "请先选择仓库。")
            return
        self.run_cli_for_repo(command, self.repo, extra_args, safe_action=safe_action)

    def run_cli_for_repo(self, command: str, repo: str, extra_args: list[str] | None = None, *, safe_action: str | None = None) -> None:
        extra_args = extra_args or []
        allowed, reason = is_command_allowed_in_gui(command, extra_args, safe_action=safe_action)
        if not allowed:
            QMessageBox.warning(self, "仅允许预览", reason)
            return
        full_command = build_cli_command(self.python_path, command, repo, extra_args)
        self.append_log(f"\n$ {' '.join(full_command)}\n")
        self.last_action.setText(f"最近操作：{command_label(command)}")
        self.runner.run(full_command)

    def append_log(self, text: str) -> None:
        self.tools.append_log(text)

    def _task_started(self, command: str) -> None:
        self.task_status.setText("任务：运行中")
        self.status.showMessage(command)

    def _task_finished(self, code: int) -> None:
        self.task_status.setText(f"任务：结束 {code}")
        self.refresh_all()
