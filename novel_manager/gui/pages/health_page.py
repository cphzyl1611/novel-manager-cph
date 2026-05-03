from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QHBoxLayout, QLabel, QMessageBox, QPushButton, QTableWidget, QTableWidgetItem, QTextEdit, QVBoxLayout, QWidget

from ..i18n import risk_label, severity_label
from ..report_loaders import find_latest_report, health_advice, load_health_report
from ..repo_state import open_in_system


class HealthPage(QWidget):  # pragma: no cover
    def __init__(self, run_command, parent=None):
        super().__init__(parent)
        self.run_command = run_command
        self.repo = None
        self.report_path = None
        self.rows: list[dict] = []
        layout = QVBoxLayout(self)
        buttons = QHBoxLayout()
        for text, cb in [
            ("运行健康检查", lambda: self.run_command("post-rename-check", [])),
            ("加载最新健康报告", self.load_latest),
            ("预览刷新元数据", lambda: self.run_command("refresh-metadata", ["--dry-run"])),
            ("执行刷新元数据", self.apply_refresh_metadata),
            ("打开报告文件", self.open_report),
            ("打开报告目录", self.open_dir),
        ]:
            b = QPushButton(text)
            b.clicked.connect(cb)
            buttons.addWidget(b)
        layout.addLayout(buttons)
        self.empty = QLabel("")
        layout.addWidget(self.empty)
        body = QHBoxLayout()
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["级别", "问题类型", "编号", "文件", "路径", "说明"])
        self.table.itemSelectionChanged.connect(self._selection_changed)
        body.addWidget(self.table, 3)
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.addWidget(QLabel("处理建议"))
        self.detail = QTextEdit("请选择一个健康检查问题。")
        self.detail.setReadOnly(True)
        right_layout.addWidget(self.detail)
        body.addWidget(right, 1)
        layout.addLayout(body)

    def refresh(self, repo: str | None = None) -> None:
        if repo is not None:
            self.repo = repo
        self.load_latest()

    def load_latest(self) -> None:
        if not self.repo:
            return
        self.report_path = find_latest_report(self.repo, "health")
        self.rows = load_health_report(self.report_path).get("issues", [])
        self.table.setRowCount(len(self.rows))
        for r, item in enumerate(self.rows):
            values = [severity_label(item.get("severity")), risk_label(item.get("code")), item.get("book_id"), item.get("file_name"), item.get("current_path"), item.get("message")]
            for c, value in enumerate(values):
                self.table.setItem(r, c, QTableWidgetItem(str(value or "")))
        self.empty.setText("还没有健康检查结果。点击“运行健康检查”开始分析。" if not self.rows else "")

    def _selection_changed(self) -> None:
        row = self.table.currentRow()
        if 0 <= row < len(self.rows):
            self.detail.setPlainText(health_advice(self.rows[row]))

    def open_report(self) -> None:
        if self.report_path:
            html = Path(str(self.report_path)).with_suffix(".html")
            open_in_system(html if html.exists() else self.report_path)

    def open_dir(self) -> None:
        if self.report_path:
            open_in_system(Path(str(self.report_path)).parent)

    def apply_refresh_metadata(self) -> None:
        text = (
            "只更新数据库中的标题和作者字段，不会修改 TXT 文件。\n\n"
            "安全说明：\n"
            "- 不会永久删除文件\n"
            "- 不会覆盖已有文件\n"
            "- 不会修改 TXT 内容\n"
            "- 操作会写入日志\n"
            "- 如需恢复，可根据操作记录手动恢复"
        )
        if QMessageBox.question(self, "执行刷新元数据", text) == QMessageBox.Yes:
            self.run_command("refresh-metadata", ["--apply"], safe_action="refresh_metadata")
            QMessageBox.information(self, "刷新任务已启动", "操作完成后页面会自动刷新。")
