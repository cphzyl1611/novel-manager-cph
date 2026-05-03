from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QCheckBox, QComboBox, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QMessageBox, QPushButton, QSpinBox, QTableWidget, QTableWidgetItem, QTextEdit, QVBoxLayout, QWidget

from ..i18n import AREA_LABELS, area_label, quality_label
from ..repo_state import load_books, open_file, open_parent_folder


class BooksPage(QWidget):  # pragma: no cover
    def __init__(self, run_command, parent=None):
        super().__init__(parent)
        self.run_command = run_command
        self.repo = None
        self.rows: list[dict] = []
        layout = QVBoxLayout(self)
        filters = QHBoxLayout()
        self.query = QLineEdit()
        self.query.setPlaceholderText("搜索书名、作者、路径")
        self.area = QComboBox()
        for value in ["all", "library", "incoming", "archive", "review_duplicates", "trash"]:
            self.area.addItem(AREA_LABELS[value], value)
        self.tag = QLineEdit()
        self.tag.setPlaceholderText("按标签过滤")
        self.status = QComboBox()
        self.status.addItems(["全部状态", "未读", "正在读", "已读", "弃书", "想重读", "待整理"])
        self.min_quality = QSpinBox()
        self.min_quality.setRange(0, 100)
        self.max_quality = QSpinBox()
        self.max_quality.setRange(0, 100)
        self.max_quality.setValue(100)
        self.problem_only = QCheckBox("只看问题小说")
        self.search_button = QPushButton("查询")
        self.search_button.clicked.connect(self.refresh)
        for widget in [QLabel("关键词"), self.query, QLabel("区域"), self.area, QLabel("标签"), self.tag, QLabel("阅读状态"), self.status, QLabel("质量分"), self.min_quality, self.max_quality, self.problem_only, self.search_button]:
            filters.addWidget(widget)
        layout.addLayout(filters)

        body = QHBoxLayout()
        self.columns = ["id", "file_name", "title_norm", "author_norm", "repo_area", "quality_score", "quality_level", "chapter_count", "tags", "reading_status"]
        self.table = QTableWidget(0, len(self.columns))
        self.table.setHorizontalHeaderLabels(["编号", "文件名", "书名", "作者", "区域", "质量分", "质量等级", "章节数", "标签", "阅读状态"])
        self.table.itemSelectionChanged.connect(self._selection_changed)
        body.addWidget(self.table, 3)

        detail_panel = QWidget()
        detail_layout = QVBoxLayout(detail_panel)
        detail_layout.addWidget(QLabel("小说详情"))
        self.detail = QTextEdit("请选择一本小说查看详情。")
        self.detail.setReadOnly(True)
        detail_layout.addWidget(self.detail)
        for text, handler in [
            ("打开小说", self.open_selected_file),
            ("打开所在文件夹", self.open_dir),
            ("复制路径", self.copy_path),
            ("移入废弃区", self.move_to_trash),
            ("设置阅读状态", self.status_selected),
            ("添加标签", self.tag_selected),
        ]:
            button = QPushButton(text)
            button.clicked.connect(handler)
            detail_layout.addWidget(button)
        body.addWidget(detail_panel, 1)
        layout.addLayout(body)

    def refresh(self, repo: str | None = None) -> None:
        if repo is not None:
            self.repo = repo
        status = self.status.currentText()
        filters = {
            "area": self.area.currentData(),
            "query": self.query.text().strip(),
            "tag": self.tag.text().strip(),
            "status": "" if status == "全部状态" else status,
            "min_quality": self.min_quality.value(),
            "max_quality": self.max_quality.value(),
            "problem_only": self.problem_only.isChecked(),
            "limit": 500,
        }
        self.rows = load_books(self.repo, filters) if self.repo else []
        self.table.setRowCount(len(self.rows))
        for r, row in enumerate(self.rows):
            for c, key in enumerate(self.columns):
                value = row.get(key)
                if key == "repo_area":
                    value = area_label(value)
                elif key == "quality_level":
                    value = quality_label(value)
                elif key == "quality_score":
                    value = f"{float(value or 0):.1f}"
                item = QTableWidgetItem(str(value or ""))
                item.setData(Qt.UserRole, row.get("id"))
                self.table.setItem(r, c, item)
        if not self.rows:
            self.detail.setPlainText("当前筛选条件下没有小说。可以先扫描小说库，或放宽筛选条件。")
        elif self.table.currentRow() < 0:
            self.detail.setPlainText("请选择一本小说查看详情。")

    def selected_book(self) -> dict | None:
        row = self.table.currentRow()
        return self.rows[row] if 0 <= row < len(self.rows) else None

    def _selection_changed(self) -> None:
        row = self.selected_book()
        if not row:
            self.detail.setPlainText("请选择一本小说查看详情。")
            return
        self.detail.setPlainText(
            "\n".join(
                [
                    f"书名：{row.get('title_norm') or '-'}",
                    f"作者：{row.get('author_norm') or '-'}",
                    f"文件名：{row.get('file_name') or '-'}",
                    f"所在区域：{area_label(row.get('repo_area'))}",
                    f"质量分：{row.get('quality_score') or 0}",
                    f"质量等级：{quality_label(row.get('quality_level'))}",
                    f"章节数：{row.get('chapter_count') or 0}",
                    f"标签：{row.get('tags') or '-'}",
                    f"阅读状态：{row.get('reading_status') or '-'}",
                    f"路径：{row.get('current_path') or '-'}",
                ]
            )
        )

    def tag_selected(self) -> None:
        row = self.selected_book()
        if not row:
            return
        tag, ok = QInputDialog.getText(self, "添加标签", "标签名：")
        if ok and tag.strip():
            self.run_command("tag-book", ["--book-id", str(row["id"]), "--tag", tag.strip(), "--create"])

    def status_selected(self) -> None:
        row = self.selected_book()
        if not row:
            return
        status, ok = QInputDialog.getItem(self, "设置阅读状态", "阅读状态：", ["未读", "正在读", "已读", "弃书", "想重读", "待整理"], editable=False)
        if ok and status:
            self.run_command("set-status", ["--book-id", str(row["id"]), "--status", status])

    def open_selected_file(self) -> None:
        row = self.selected_book()
        if row:
            ok, message = open_file(row.get("current_path") or "")
            if not ok:
                QMessageBox.warning(self, "无法打开小说", message)

    def open_dir(self) -> None:
        row = self.selected_book()
        if row:
            ok, message = open_parent_folder(row.get("current_path") or "")
            if not ok:
                QMessageBox.warning(self, "无法打开所在文件夹", message)

    def copy_path(self) -> None:
        row = self.selected_book()
        if row:
            QApplication.clipboard().setText(str(row.get("current_path") or ""))
            self.detail.append("\n路径已复制。")

    def move_to_trash(self) -> None:
        row = self.selected_book()
        if not row:
            return
        text = (
            f"将把这本小说移入废弃区：\n{row.get('file_name')}\n\n"
            "安全说明：\n"
            "- 不会永久删除文件\n"
            "- 不会覆盖已有文件\n"
            "- 不会修改 TXT 内容\n"
            "- 操作会写入日志\n"
            "- 如需恢复，可根据操作记录手动恢复"
        )
        if QMessageBox.question(self, "移入废弃区", text) == QMessageBox.Yes:
            self.run_command("move-to-trash", ["--book-id", str(row["id"]), "--confirm", "--yes-i-understand"], safe_action="move_single_book_to_trash")
