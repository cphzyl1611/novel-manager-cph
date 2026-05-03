from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMessageBox, QPushButton, QTextEdit, QVBoxLayout, QWidget

from ..i18n import action_label, risks_label
from ..report_loaders import find_latest_report, load_update_report
from ..repo_state import open_file, open_in_system, open_parent_folder
from ..safe_actions import is_safe_update_item, write_filtered_update_report


class UpdatePage(QWidget):  # pragma: no cover
    def __init__(self, run_command, parent=None):
        super().__init__(parent)
        self.run_command = run_command
        self.repo = None
        self.report_path = None
        self.rows: list[dict] = []
        self.selected_indexes: set[int] = set()
        layout = QVBoxLayout(self)
        buttons = QHBoxLayout()
        for text, cb in [
            ("运行更新检测", lambda: self.run_command("check-updates", [])),
            ("加载最新报告", self.load_latest),
            ("一键选择建议更新项", self.select_safe_updates),
            ("预览推荐更新", self.preview_selected),
            ("执行推荐更新", self.apply_selected),
            ("打开详细报告", self.open_report),
        ]:
            b = QPushButton(text)
            b.clicked.connect(cb)
            buttons.addWidget(b)
            if text == "执行推荐更新":
                self.apply_button = b
        layout.addLayout(buttons)
        self.empty = QLabel("")
        layout.addWidget(self.empty)
        body = QHBoxLayout()
        self.list = QListWidget()
        self.list.itemSelectionChanged.connect(self._selection_changed)
        body.addWidget(self.list, 1)
        compare = QWidget()
        compare_layout = QHBoxLayout(compare)
        self.old_card = QTextEdit()
        self.old_card.setReadOnly(True)
        self.new_card = QTextEdit()
        self.new_card.setReadOnly(True)
        compare_layout.addWidget(self.old_card)
        compare_layout.addWidget(self.new_card)
        body.addWidget(compare, 2)
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.addWidget(QLabel("推荐结论"))
        self.detail = QTextEdit()
        self.detail.setReadOnly(True)
        right_layout.addWidget(self.detail)
        for text, cb in [
            ("打开旧版", lambda: self._open_path("old_path")),
            ("打开新版", lambda: self._open_path("new_path")),
            ("打开所在文件夹", self._open_dir),
            ("打开报告目录", self.open_dir),
        ]:
            b = QPushButton(text)
            b.clicked.connect(cb)
            right_layout.addWidget(b)
        body.addWidget(right, 1)
        layout.addLayout(body)

    def refresh(self, repo: str | None = None) -> None:
        if repo is not None:
            self.repo = repo
        self.load_latest()

    def load_latest(self) -> None:
        if not self.repo:
            return
        self.report_path = find_latest_report(self.repo, "update")
        self.rows = load_update_report(self.report_path).get("candidates", [])
        self.selected_indexes = {i for i, item in enumerate(self.rows) if is_safe_update_item(item)}
        self.list.clear()
        for index, item in enumerate(self.rows):
            text = f"{item.get('old_file') or item.get('old_title') or '当前库版本'}\n→ {item.get('new_file') or item.get('new_title') or '新下载版本'} · {action_label(item.get('recommendation'))}"
            row = QListWidgetItem(text)
            row.setData(32, index)
            row.setCheckState(Qt.Checked if index in self.selected_indexes else Qt.Unchecked)
            self.list.addItem(row)
        safe_count = sum(1 for item in self.rows if is_safe_update_item(item))
        self.apply_button.setEnabled(safe_count > 0)
        if not self.rows:
            self.empty.setText("新下载区暂无候选文件。把新下载的 TXT 放入 incoming 后再运行更新检测。")
        elif safe_count == 0:
            self.empty.setText("当前没有可安全执行的推荐更新。")
        else:
            self.empty.setText("")
        if self.rows:
            self.list.setCurrentRow(0)

    def selected(self) -> dict | None:
        item = self.list.currentItem()
        if not item:
            return None
        index = item.data(32)
        return self.rows[index] if 0 <= index < len(self.rows) else None

    def selected_safe_rows(self) -> list[dict]:
        rows = []
        for i in range(self.list.count()):
            item = self.list.item(i)
            index = item.data(32)
            row = self.rows[index]
            if item.checkState() == Qt.Checked and is_safe_update_item(row):
                rows.append(row)
        return rows

    def select_safe_updates(self) -> None:
        for i in range(self.list.count()):
            item = self.list.item(i)
            item.setCheckState(Qt.Checked if is_safe_update_item(self.rows[item.data(32)]) else Qt.Unchecked)

    def _selection_changed(self) -> None:
        item = self.selected()
        if not item:
            self.old_card.setPlainText("")
            self.new_card.setPlainText("")
            self.detail.setPlainText("请选择一个更新候选。")
            return
        self.old_card.setPlainText(self._book_card("当前库版本", item, "old"))
        self.new_card.setPlainText(self._book_card("新下载版本", item, "new"))
        self.detail.setPlainText(
            "\n".join(
                [
                    f"推荐动作：{action_label(item.get('recommendation'))}",
                    f"同书分：{item.get('same_work_score') or '-'}",
                    f"覆盖率：{item.get('coverage_score') or '-'}",
                    f"新增内容：{item.get('new_content_score') or '-'}",
                    f"质量变化：{item.get('quality_delta') or 0}",
                    f"风险提示：{risks_label(item.get('risk_flags')) or '未发现明显风险'}",
                    f"解释说明：{item.get('reason_summary') or '请结合章节数、字数和质量变化人工确认。'}",
                    f"是否可安全执行：{'是' if is_safe_update_item(item) else '否，需要人工确认'}",
                ]
            )
        )

    def _book_card(self, title: str, item: dict, prefix: str) -> str:
        return "\n".join(
            [
                title,
                f"文件名：{item.get(prefix + '_file') or '-'}",
                f"章节数：{item.get(prefix + '_chapter_count') or '-'}",
                f"字数：{item.get(prefix + '_char_count_clean') or item.get(prefix + '_char_count') or '-'}",
                f"质量分：{item.get(prefix + '_quality_score') or '-'}",
                f"路径：{item.get(prefix + '_path') or '-'}",
            ]
        )

    def _filtered_report_or_warn(self) -> Path | None:
        if not self.repo or not self.report_path:
            return None
        selected = self.selected_safe_rows()
        if not selected:
            QMessageBox.information(self, "没有可执行项", "当前没有已选择的安全更新项。")
            return None
        return write_filtered_update_report(self.repo, self.report_path, selected)

    def preview_selected(self) -> None:
        path = self._filtered_report_or_warn()
        if path:
            self.run_command("apply-updates", ["--report", str(path), "--dry-run"])

    def apply_selected(self) -> None:
        path = self._filtered_report_or_warn()
        if not path:
            return
        count = len(load_update_report(path).get("candidates", []))
        text = (
            f"将执行推荐更新：{count} 本。\n\n"
            "旧版会进入归档区，新版会进入小说库。\n\n"
            "安全说明：\n"
            "- 不会永久删除文件\n"
            "- 不会覆盖已有文件\n"
            "- 不会修改 TXT 内容\n"
            "- 操作会写入日志\n"
            "- 如需恢复，可根据操作记录手动恢复"
        )
        if QMessageBox.question(self, "执行推荐更新", text) == QMessageBox.Yes:
            self.run_command("apply-updates", ["--report", str(path), "--confirm", "--yes-i-understand"], safe_action="apply_recommended_updates")
            QMessageBox.information(self, "更新任务已启动", "操作完成后页面会自动刷新。可到“操作记录”查看日志。")

    def _open_path(self, key: str) -> None:
        if item := self.selected():
            open_file(item.get(key) or "")

    def _open_dir(self) -> None:
        if item := self.selected():
            open_parent_folder(item.get("new_path") or item.get("old_path") or "")

    def open_report(self) -> None:
        if self.report_path:
            html = Path(str(self.report_path)).with_suffix(".html")
            open_in_system(html if html.exists() else self.report_path)

    def open_dir(self) -> None:
        if self.report_path:
            open_in_system(Path(str(self.report_path)).parent)
