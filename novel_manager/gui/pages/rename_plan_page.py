from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QSignalBlocker
from PySide6.QtGui import QBrush
from PySide6.QtWidgets import (
    QComboBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ..i18n import action_label, risks_label
from ..report_loaders import find_latest_report, load_rename_plan, summarize_report
from ..repo_state import open_in_system
from ..safe_actions import (
    can_apply_visible_rows,
    compute_rename_stats,
    get_rename_row_status,
    initial_checked_keys,
    is_row_checked,
    is_safe_rename_item,
    row_key,
    update_checked_keys,
    write_filtered_rename_plan,
)
from ..widgets import StatCard


class RenamePlanPage(QWidget):  # pragma: no cover
    def __init__(self, run_command, parent=None):
        super().__init__(parent)
        self.run_command = run_command
        self.repo = None
        self.report_path = None
        self.rows: list[dict] = []
        self.visible_rows: list[dict] = []
        self.checked_row_keys: set[str] = set()

        layout = QVBoxLayout(self)

        # --- stat cards ---
        stats = QGridLayout()
        self.cards = {
            "rename_recommended": StatCard("建议改名"),
            "manual_review": StatCard("需确认"),
            "conflict": StatCard("冲突"),
            "no_change": StatCard("无需修改"),
        }
        for index, card in enumerate(self.cards.values()):
            stats.addWidget(card, 0, index)
        layout.addLayout(stats)

        # --- button bar ---
        buttons = QHBoxLayout()
        self.filter = QComboBox()
        for value, text in [
            ("all", "全部"),
            ("rename_recommended", "可安全改名"),
            ("manual_review", "需确认"),
            ("conflict", "冲突"),
            ("no_change", "无需修改"),
        ]:
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
            elif text == "预览改名操作":
                self.preview_button = b
        buttons.addWidget(self.filter)
        layout.addLayout(buttons)

        # --- info label ---
        self.empty = QLabel("")
        layout.addWidget(self.empty)

        # --- stats bar ---
        stats_bar = QHBoxLayout()
        self.stats_label = QLabel("当前计划：加载中...")
        self.stats_label.setWordWrap(True)
        stats_bar.addWidget(self.stats_label)
        stats_bar.addStretch()
        layout.addLayout(stats_bar)

        # --- table + detail body ---
        body = QHBoxLayout()
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(
            ["处理状态", "小说编号", "当前文件名", "建议文件名", "处理建议", "风险提示", "原因"]
        )
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setColumnWidth(0, 100)
        self.table.itemClicked.connect(self._on_item_clicked)
        self.table.currentCellChanged.connect(self._selection_changed)
        body.addWidget(self.table, 3)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.addWidget(QLabel("文件名详情"))
        self.detail = QTextEdit("还没有选择文件名建议。")
        self.detail.setReadOnly(True)
        right_layout.addWidget(self.detail)
        body.addWidget(right, 1)
        layout.addLayout(body)

    # ------------------------------------------------------------------
    # data loading
    # ------------------------------------------------------------------

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
        self.checked_row_keys = initial_checked_keys(self.rows)
        stats = summarize_report(data)
        for key, card in self.cards.items():
            card.set_value(stats.get(key, 0))
        self.empty.setText(
            '还没有重命名计划。点击"生成重命名计划"查看建议。' if not self.rows else ""
        )
        self._populate()

    # ------------------------------------------------------------------
    # filtering
    # ------------------------------------------------------------------

    def _filtered(self) -> list[dict]:
        mode = self.filter.currentData()
        if mode == "all":
            return self.rows
        if mode == "conflict":
            return [
                r
                for r in self.rows
                if "target_name_conflict" in (r.get("risk_flags") or [])
            ]
        return [r for r in self.rows if r.get("action") == mode]

    # ------------------------------------------------------------------
    # table population
    # ------------------------------------------------------------------

    def _populate(self) -> None:
        self.visible_rows = self._filtered()

        with QSignalBlocker(self.table):
            self.table.setRowCount(len(self.visible_rows))

            for r, item in enumerate(self.visible_rows):
                row_status = get_rename_row_status(item)
                checkable = row_status["checkable"]

                # --- first column: 处理状态 ---
                status_text = row_status["status_text"]
                if checkable and not status_text:
                    status_text = ""  # safe items show a checkbox instead of text
                elif not checkable and not status_text:
                    status_text = "不可处理"

                first = QTableWidgetItem(status_text)
                if checkable:
                    first.setFlags(
                        Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsUserCheckable
                    )
                    checked = is_row_checked(item, self.checked_row_keys)
                    first.setCheckState(Qt.Checked if checked else Qt.Unchecked)
                    first.setTextAlignment(Qt.AlignCenter)
                else:
                    first.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                    first.setForeground(QBrush(Qt.GlobalColor.gray))
                    first.setTextAlignment(Qt.AlignCenter)
                first.setToolTip(row_status["reason"])
                first.setData(Qt.UserRole, item.get("book_id"))
                self.table.setItem(r, 0, first)

                # --- remaining columns ---
                values = [
                    item.get("book_id"),
                    item.get("current_file_name"),
                    item.get("target_file_name"),
                    action_label(item.get("action")),
                    risks_label(item.get("risk_flags")),
                    item.get("reason_summary"),
                ]
                for c, value in enumerate(values, start=1):
                    cell = QTableWidgetItem(str(value or ""))
                    cell.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                    self.table.setItem(r, c, cell)

        self._update_button_state()
        self._refresh_stats()

    # ------------------------------------------------------------------
    # button state
    # ------------------------------------------------------------------

    def _update_button_state(self) -> None:
        can_apply = can_apply_visible_rows(self.visible_rows, self.checked_row_keys)
        has_any_safe = any(
            get_rename_row_status(r)["category"] == "safe" for r in self.visible_rows
        )
        self.preview_button.setEnabled(has_any_safe)
        self.apply_button.setEnabled(can_apply)

    # ------------------------------------------------------------------
    # stats bar
    # ------------------------------------------------------------------

    def _refresh_stats(self) -> None:
        s = compute_rename_stats(self.visible_rows, self.checked_row_keys)
        self.stats_label.setText(
            f"总数 {s['total']}  |  可安全处理 {s['safe']}  |  已勾选 {s['checked']}  |"
            f"  需确认 {s['manual']}  |  冲突 {s['conflict']}  |  无需修改 {s['no_change']}"
        )

    # ------------------------------------------------------------------
    # checkbox toggling (click handling)
    # ------------------------------------------------------------------

    def _on_item_clicked(self, item: QTableWidgetItem) -> None:
        if item.column() != 0:
            return
        row = item.row()
        if not (0 <= row < len(self.visible_rows)):
            return
        row_data = self.visible_rows[row]
        row_status = get_rename_row_status(row_data)
        if not row_status["checkable"]:
            return
        self.checked_row_keys = update_checked_keys(
            self.checked_row_keys, row_data, item.checkState() == Qt.Checked
        )
        self._update_button_state()
        self._refresh_stats()

    # ------------------------------------------------------------------
    # checkbox batch operations
    # ------------------------------------------------------------------

    def select_safe_items(self) -> None:
        safe_count = sum(
            1 for row in self.visible_rows if is_safe_rename_item(row)
        )
        if safe_count == 0:
            QMessageBox.information(
                self,
                "没有安全项",
                "当前没有可安全处理的改名项。请重新生成重命名计划，或人工处理冲突项。",
            )
            return

        for row_data in self.visible_rows:
            if is_safe_rename_item(row_data):
                self.checked_row_keys.add(row_key(row_data))
            else:
                self.checked_row_keys.discard(row_key(row_data))

        with QSignalBlocker(self.table):
            for r, row_data in enumerate(self.visible_rows):
                first = self.table.item(r, 0)
                if first and (first.flags() & Qt.ItemIsUserCheckable):
                    first.setCheckState(
                        Qt.Checked
                        if is_safe_rename_item(row_data)
                        else Qt.Unchecked
                    )
        self._update_button_state()
        self._refresh_stats()

    def clear_selection(self) -> None:
        for row_data in self.visible_rows:
            self.checked_row_keys.discard(row_key(row_data))

        with QSignalBlocker(self.table):
            for r in range(self.table.rowCount()):
                first = self.table.item(r, 0)
                if first and (first.flags() & Qt.ItemIsUserCheckable):
                    first.setCheckState(Qt.Unchecked)
        self._update_button_state()
        self._refresh_stats()

    # ------------------------------------------------------------------
    # detail pane
    # ------------------------------------------------------------------

    def _selection_changed(
        self, row: int, _col: int, _prev_row: int, _prev_col: int
    ) -> None:
        if not (0 <= row < len(self.visible_rows)):
            return
        item = self.visible_rows[row]
        row_status = get_rename_row_status(item)

        is_checked = is_row_checked(item, self.checked_row_keys)

        lines = [
            f"当前文件名：{item.get('current_file_name') or '-'}",
            f"建议文件名：{item.get('target_file_name') or '-'}",
            f"当前路径：{item.get('current_path') or '-'}",
            f"目标路径：{item.get('target_path_preview') or '-'}",
            f"处理建议：{action_label(item.get('action'))}",
            f"风险提示：{risks_label(item.get('risk_flags')) or '未发现明显风险'}",
            f"原因说明：{item.get('reason_summary') or '-'}",
            "",
            f"是否可安全处理：{'是' if row_status['checkable'] else '否'}",
            f"当前是否纳入执行：{'是' if is_checked else '否'}",
        ]
        if not row_status["checkable"]:
            lines.append(f"不可处理原因：{row_status['reason']}")
            lines.append("")
            lines.append("此项不会被一键处理，需要人工确认。")
        else:
            lines.append("")
            lines.append(
                "此项可安全处理，点击左侧复选框可纳入或移出执行列表。"
            )
        self.detail.setPlainText("\n".join(lines))

    # ------------------------------------------------------------------
    # filtered report helpers
    # ------------------------------------------------------------------

    def selected_safe_rows(self) -> list[dict]:
        selected = []
        for row_data in self.visible_rows:
            if is_row_checked(row_data, self.checked_row_keys) and is_safe_rename_item(row_data):
                selected.append(row_data)
        return selected

    def _filtered_report_or_warn(self) -> Path | None:
        if not self.repo or not self.report_path:
            return None
        selected = self.selected_safe_rows()
        if not selected:
            QMessageBox.information(
                self, "没有可执行项", "当前没有已勾选的安全改名项。"
            )
            return None
        return write_filtered_rename_plan(self.repo, self.report_path, selected)

    def preview_selected(self) -> None:
        path = self._filtered_report_or_warn()
        if path:
            self.run_command(
                "apply-renames", ["--report", str(path), "--dry-run"]
            )

    def apply_selected(self) -> None:
        path = self._filtered_report_or_warn()
        if not path:
            return
        count = len(load_rename_plan(path).get("suggestions", []))
        s = compute_rename_stats(self.visible_rows, self.checked_row_keys)
        text = (
            f"将执行已勾选的安全改名：{count} 项。\n"
            f"未勾选的安全项：{s['unselected_safe']} 项。\n"
            f"跳过需确认项：{s['manual']} 项。\n"
            f"跳过冲突项：{s['conflict']} 项。\n"
            f"跳过无需修改项：{s['no_change']} 项。\n\n"
            "安全说明：\n"
            "- 不会永久删除文件\n"
            "- 不会覆盖已有文件\n"
            "- 不会修改 TXT 内容\n"
            "- 操作会写入日志\n"
            "- 如需恢复，可根据操作记录手动恢复"
        )
        if QMessageBox.question(self, "执行已勾选改名", text) == QMessageBox.Yes:
            self.run_command(
                "apply-renames",
                ["--report", str(path), "--confirm", "--yes-i-understand"],
                safe_action="apply_selected_renames",
            )
            QMessageBox.information(
                self,
                "改名任务已启动",
                '操作完成后页面会自动刷新。可到"操作记录"查看日志。',
            )

    def open_report(self) -> None:
        if self.report_path:
            html = Path(str(self.report_path)).with_suffix(".html")
            open_in_system(html if html.exists() else self.report_path)

    def open_dir(self) -> None:
        if self.report_path:
            open_in_system(Path(str(self.report_path)).parent)
