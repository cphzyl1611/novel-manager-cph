from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QPushButton, QTableWidget, QTableWidgetItem, QTextEdit, QVBoxLayout, QWidget

from ..repo_state import load_group_members, load_groups


class GroupsPage(QWidget):  # pragma: no cover
    def __init__(self, run_command, parent=None):
        super().__init__(parent)
        self.run_command = run_command
        self.repo = None
        self.groups: list[dict] = []
        layout = QVBoxLayout(self)
        buttons = QHBoxLayout()
        refresh = QPushButton("刷新分组")
        refresh.clicked.connect(self.refresh)
        generate = QPushButton("生成分组报告")
        generate.clicked.connect(lambda: self.run_command("group-books", []))
        inspect = QPushButton("查看分组详情")
        inspect.clicked.connect(self.inspect_group)
        for button in [refresh, generate, inspect]:
            buttons.addWidget(button)
        layout.addLayout(buttons)
        body = QHBoxLayout()
        self.group_table = QTableWidget(0, 5)
        self.group_table.setHorizontalHeaderLabels(["group_id", "书名", "作者", "版本数", "置信度"])
        self.group_table.itemSelectionChanged.connect(self._selection_changed)
        body.addWidget(self.group_table, 1)
        self.member_table = QTableWidget(0, 8)
        self.member_table.setHorizontalHeaderLabels(["book_id", "file_name", "role", "quality", "chapters", "chars", "area", "path"])
        body.addWidget(self.member_table, 2)
        self.detail = QTextEdit()
        self.detail.setReadOnly(True)
        body.addWidget(self.detail, 1)
        layout.addLayout(body)

    def refresh(self, repo: str | None = None) -> None:
        if repo is not None:
            self.repo = repo
        self.groups = load_groups(self.repo) if self.repo else []
        self.group_table.setRowCount(len(self.groups))
        for r, group in enumerate(self.groups):
            values = [group.get("id"), group.get("canonical_title"), group.get("canonical_author"), group.get("member_count"), group.get("group_confidence")]
            for c, value in enumerate(values):
                self.group_table.setItem(r, c, QTableWidgetItem(str(value or "")))

    def selected_group(self) -> dict | None:
        row = self.group_table.currentRow()
        return self.groups[row] if 0 <= row < len(self.groups) else None

    def _selection_changed(self) -> None:
        group = self.selected_group()
        if not group or not self.repo:
            return
        members = load_group_members(self.repo, int(group["id"]))
        self.member_table.setRowCount(len(members))
        for r, item in enumerate(members):
            values = [item.get("book_id"), item.get("file_name"), item.get("role"), item.get("quality_score"), item.get("chapter_count"), item.get("char_count_clean"), item.get("repo_area"), item.get("current_path")]
            for c, value in enumerate(values):
                self.member_table.setItem(r, c, QTableWidgetItem(str(value or "")))
        self.detail.setPlainText(
            f"同书版本说明：这里表示同一本小说的不同 TXT 版本集合，不是用户自定义分组。\nprimary_book_id: {group.get('primary_book_id')}\nsource: {group.get('group_source')}\ndescription: {group.get('description') or ''}"
        )

    def inspect_group(self) -> None:
        group = self.selected_group()
        if group:
            self.run_command("inspect-group", ["--group-id", str(group["id"])])
