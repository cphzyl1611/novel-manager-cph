from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QLabel, QComboBox, QHBoxLayout, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget

from ..i18n import REPORT_LABELS, report_label
from ..repo_state import load_reports, open_in_system


class ReportsPage(QWidget):  # pragma: no cover
    def __init__(self, run_command, parent=None):
        super().__init__(parent)
        self.run_command = run_command
        self.repo = None
        self.rows: list[dict] = []
        layout = QVBoxLayout(self)
        info = QLabel("历史报告用于回看已经生成的检查结果。日常处理建议从“待处理事项”进入。")
        info.setWordWrap(True)
        layout.addWidget(info)
        tools = QHBoxLayout()
        self.type_combo = QComboBox()
        self.type_combo.addItem("全部报告", "all")
        for key in ["duplicate", "quality", "errors", "summary", "diagnostic", "update", "group", "rename", "health"]:
            self.type_combo.addItem(REPORT_LABELS.get(key, key), key)
        for widget in [
            self.type_combo,
            self._button("刷新", self.refresh),
            self._button("打开报告", self.open_selected),
            self._button("打开所在目录", self.open_folder),
            self._button("刷新报告索引", lambda: self.run_command("report-index", [])),
            self._button("打开最新汇总报告", lambda: self.run_command("open-latest-report", ["--type", "summary"])),
        ]:
            tools.addWidget(widget)
        layout.addLayout(tools)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["文件名", "报告类型", "格式", "大小", "修改时间", "路径"])
        layout.addWidget(self.table)
        self.empty = QLabel("")
        layout.addWidget(self.empty)

    def _button(self, text: str, cb):
        button = QPushButton(text)
        button.clicked.connect(cb)
        return button

    def refresh(self, repo: str | None = None) -> None:
        if repo is not None:
            self.repo = repo
        self.rows = load_reports(self.repo, self.type_combo.currentData()) if self.repo else []
        self.table.setRowCount(len(self.rows))
        for r, item in enumerate(self.rows):
            values = [item["file_name"], report_label(item["report_type"]), item["suffix"], item["size"], item["modified_time"], item["path"]]
            for c, value in enumerate(values):
                self.table.setItem(r, c, QTableWidgetItem(str(value)))
        self.empty.setText("暂无历史报告。可以先运行重复检测、更新检测、文件名整理或健康检查。" if not self.rows else "")

    def selected(self) -> dict | None:
        row = self.table.currentRow()
        return self.rows[row] if 0 <= row < len(self.rows) else None

    def open_selected(self) -> None:
        item = self.selected()
        if item:
            open_in_system(item["path"])

    def open_folder(self) -> None:
        item = self.selected()
        if item:
            open_in_system(Path(item["path"]).parent)
