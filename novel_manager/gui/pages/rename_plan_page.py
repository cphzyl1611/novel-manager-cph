from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QCheckBox, QComboBox, QGridLayout, QHBoxLayout, QLabel, QMessageBox, QPushButton, QTableWidget, QTableWidgetItem, QTextEdit, QVBoxLayout, QWidget

from ..i18n import action_label, risks_label
from ..report_loaders import find_latest_report, load_rename_plan, summarize_report
from ..repo_state import open_in_system
from ..safe_actions import is_safe_rename_item, write_filtered_rename_plan
from ..widgets import StatCard


class RenamePlanPage(QWidget):  # pragma: no cover
    def __init__(self, run_command, parent=None):
        super().__init__(parent)
        self.run_command = run_command
        self.repo = None
        self.report_path = None
        self.rows: list[dict] = []
        self.visible_rows: list[dict] = []
        layout = QVBoxLayout(self)
        stats = QGridLayout()
        self.cards = {
            "rename_recommended": StatCard("建议改名"),
            "manual_review": StatCard("需要确认"),
            "conflict": StatCard("冲突"),
            "no_change": StatCard("无需修改"),
        }
        for index, card in enumerate(self.cards.values()):
            stats.addWidget(card, 0, index)
        layout.addLayout(stats)

        buttons = QHBoxLayout()
        self.filter = QComboBox()
        for value, text in [("all", "全部"), ("rename_recommended", "可安全改名"), ("manual_review", "需要人工确认"), ("conflict", "文件名冲突"), ("no_change", "无需修改")]:
            self.filter.addItem(text, value)
        self.filter.currentTextChanged.connect(self._populate)
        for text, cb in [
            ("生成重命名计划", lambda: self.run_command("rename-plan", [])),
            ("加载最新计划", self.load_latest),
            ("一键勾选安全项", self.select_safe_items),
            ("取消全选", self.clear_selection),
            ("预览改名操作", self.preview_selected),
            ("执行已勾选改名", self.apply_selected),
            ("打开报告", self.open_report),
            ("打开所在目录", self.open_dir),
        ]:
            b = QPushButton(text)
            b.clicked.connect(cb)
            buttons.addWidget(b)
            if text == "执行已勾选改名":
                self.apply_button = b
        buttons.addWidget(self.filter)
        layout.addLayout(buttons)
        self.empty = QLabel("")
        layout.addWidget(self.empty)

        body = QHBoxLayout()
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(["纳入处理", "小说编号", "当前文件名", "建议文件名", "处理建议", "风险提示", "原因"])
        self.table.itemSelectionChanged.connect(self._selection_changed)
        body.addWidget(self.table, 3)
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.addWidget(QLabel("文件名详情"))
        self.detail = QTextEdit("还没有选择文件名建议。")
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
        self.report_path = find_latest_report(self.repo, "rename")
        data = load_rename_plan(self.report_path)
        self.rows = data.get("suggestions", [])
        stats = summarize_report(data)
        for key, card in self.cards.items():
            card.set_value(stats.get(key, 0))
        self.empty.setText("还没有重命名计划。点击“生成重命名计划”查看建议。" if not self.rows else "")
        self._populate()

    def _filtered(self) -> list[dict]:
        mode = self.filter.currentData()
        if mode == "all":
            return self.rows
        if mode == "conflict":
            return [r for r in self.rows if "target_name_conflict" in (r.get("risk_flags") or [])]
        return [r for r in self.rows if r.get("action") == mode]

    def _populate(self) -> None:
        self.visible_rows = self._filtered()
        self.table.setRowCount(len(self.visible_rows))
        for r, item in enumerate(self.visible_rows):
            include = QCheckBox()
            include.setChecked(is_safe_rename_item(item))
            include.setEnabled(is_safe_rename_item(item))
            self.table.setCellWidget(r, 0, include)
            values = [item.get("book_id"), item.get("current_file_name"), item.get("target_file_name"), action_label(item.get("action")), risks_label(item.get("risk_flags")), item.get("reason_summary")]
            for c, value in enumerate(values, start=1):
                self.table.setItem(r, c, QTableWidgetItem(str(value or "")))
        self.apply_button.setEnabled(any(is_safe_rename_item(row) for row in self.rows))

    def selected_safe_rows(self) -> list[dict]:
        selected = []
        for row, item in enumerate(self.visible_rows):
            widget = self.table.cellWidget(row, 0)
            if isinstance(widget, QCheckBox) and widget.isChecked() and is_safe_rename_item(item):
                selected.append(item)
        return selected

    def select_safe_items(self) -> None:
        for row, item in enumerate(self.visible_rows):
            widget = self.table.cellWidget(row, 0)
            if isinstance(widget, QCheckBox):
                widget.setChecked(is_safe_rename_item(item))

    def clear_selection(self) -> None:
        for row in range(self.table.rowCount()):
            widget = self.table.cellWidget(row, 0)
            if isinstance(widget, QCheckBox):
                widget.setChecked(False)

    def _selection_changed(self) -> None:
        row = self.table.currentRow()
        if not (0 <= row < len(self.visible_rows)):
            return
        item = self.visible_rows[row]
        safe = is_safe_rename_item(item)
        self.detail.setPlainText(
            "\n".join(
                [
                    f"当前路径：{item.get('current_path') or '-'}",
                    f"目标路径：{item.get('target_path_preview') or '-'}",
                    f"清洗后的书名：{item.get('title_cleaned') or '-'}",
                    f"作者：{item.get('author_used') or '-'}",
                    f"状态：{item.get('statuses_used') or '-'}",
                    f"风险解释：{risks_label(item.get('risk_flags')) or '未发现明显风险'}",
                    f"是否可安全执行：{'是' if safe else '否，需要人工确认'}",
                ]
            )
        )

    def _filtered_report_or_warn(self) -> Path | None:
        if not self.repo or not self.report_path:
            return None
        selected = self.selected_safe_rows()
        if not selected:
            QMessageBox.information(self, "没有可执行项", "当前没有已勾选的安全改名项。")
            return None
        return write_filtered_rename_plan(self.repo, self.report_path, selected)

    def preview_selected(self) -> None:
        path = self._filtered_report_or_warn()
        if path:
            self.run_command("apply-renames", ["--report", str(path), "--dry-run"])

    def apply_selected(self) -> None:
        path = self._filtered_report_or_warn()
        if not path:
            return
        count = len(load_rename_plan(path).get("suggestions", []))
        skipped = max(0, len(self.rows) - count)
        text = (
            f"将执行已勾选的安全改名：{count} 项。\n"
            f"跳过风险项：{skipped} 项。\n\n"
            "安全说明：\n"
            "- 不会永久删除文件\n"
            "- 不会覆盖已有文件\n"
            "- 不会修改 TXT 内容\n"
            "- 操作会写入日志\n"
            "- 如需恢复，可根据操作记录手动恢复"
        )
        if QMessageBox.question(self, "执行已勾选改名", text) == QMessageBox.Yes:
            self.run_command("apply-renames", ["--report", str(path), "--confirm", "--yes-i-understand"], safe_action="apply_selected_renames")
            QMessageBox.information(self, "改名任务已启动", "操作完成后页面会自动刷新。可到“操作记录”查看日志。")

    def open_report(self) -> None:
        if self.report_path:
            html = Path(str(self.report_path)).with_suffix(".html")
            open_in_system(html if html.exists() else self.report_path)

    def open_dir(self) -> None:
        if self.report_path:
            open_in_system(Path(str(self.report_path)).parent)
