from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtWidgets import QHBoxLayout, QListWidget, QListWidgetItem, QPushButton, QPlainTextEdit, QSplitter, QVBoxLayout, QWidget

from ..i18n import operation_label
from ..repo_state import load_recent_operation_records, open_in_system


class LogsPage(QWidget):  # pragma: no cover
    def __init__(self, parent=None):
        super().__init__(parent)
        self.repo = None
        self.records: list[dict] = []
        layout = QVBoxLayout(self)
        buttons = QHBoxLayout()
        for text, cb in [
            ("刷新", self.refresh),
            ("打开日志目录", self.open_logs_dir),
            ("打开原始日志", self.open_selected),
            ("查看原始 JSON", self.show_raw),
        ]:
            button = QPushButton(text)
            button.clicked.connect(cb)
            buttons.addWidget(button)
        layout.addLayout(buttons)
        splitter = QSplitter()
        self.items = QListWidget()
        self.items.itemSelectionChanged.connect(self._selection_changed)
        self.content = QPlainTextEdit("暂无操作记录。")
        self.content.setReadOnly(True)
        splitter.addWidget(self.items)
        splitter.addWidget(self.content)
        splitter.setSizes([320, 620])
        layout.addWidget(splitter)

    def refresh(self, repo: str | None = None) -> None:
        if repo is not None:
            self.repo = repo
        self.items.clear()
        self.records = load_recent_operation_records(self.repo, 100) if self.repo else []
        for index, record in enumerate(self.records):
            text = f"{record.get('created_at') or record.get('applied_at') or '未知时间'}\n{record.get('summary')}"
            item = QListWidgetItem(text)
            item.setData(32, index)
            self.items.addItem(item)
        if not self.records:
            self.content.setPlainText("暂无操作记录。")
        else:
            self.items.setCurrentRow(0)

    def _selected(self) -> dict | None:
        item = self.items.currentItem()
        if not item:
            return None
        index = item.data(32)
        return self.records[index] if 0 <= index < len(self.records) else None

    def _selection_changed(self) -> None:
        record = self._selected()
        if not record:
            return
        self.content.setPlainText(
            "\n".join(
                [
                    f"操作类型：{operation_label(record.get('operation_type'))}",
                    f"结果：{record.get('status') or '-'}",
                    f"影响对象：{record.get('book_id') or '-'}",
                    f"原路径：{record.get('source_path') or '-'}",
                    f"新路径：{record.get('target_path') or '-'}",
                    f"操作状态：{record.get('status') or '-'}",
                    f"是否可恢复：{'可根据日志人工恢复' if record.get('source_path') and record.get('target_path') else '未记录恢复信息'}",
                    f"日志文件路径：{record.get('log_path') or '-'}",
                ]
            )
        )

    def show_raw(self) -> None:
        record = self._selected()
        if record:
            self.content.setPlainText(json.dumps(record, ensure_ascii=False, indent=2))

    def open_logs_dir(self) -> None:
        if self.repo:
            open_in_system(Path(self.repo) / "logs")

    def open_selected(self) -> None:
        record = self._selected()
        if record and record.get("log_path"):
            open_in_system(record["log_path"])
