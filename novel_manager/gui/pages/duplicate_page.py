from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QPushButton, QTableWidget, QTableWidgetItem, QTextEdit, QVBoxLayout, QWidget

from ..i18n import action_label, area_label, group_type_label, quality_label, risks_label
from ..report_loaders import find_latest_report, load_duplicate_report
from ..repo_state import open_file, open_in_system, open_parent_folder


class DuplicatePage(QWidget):  # pragma: no cover
    def __init__(self, run_command, parent=None):
        super().__init__(parent)
        self.run_command = run_command
        self.repo = None
        self.report_path = None
        self.groups: list[dict] = []
        layout = QVBoxLayout(self)
        buttons = QHBoxLayout()
        for text, cb in [
            ("运行精确去重", lambda: self.run_command("find-duplicates", ["--mode", "exact", "--area", "all"])),
            ("运行近似去重", lambda: self.run_command("find-duplicates", ["--mode", "near", "--area", "all"])),
            ("加载最新报告", self.load_latest),
            ("一键选择可安全处理项", self.select_safe_groups),
            ("预览移入重复复核区", self.stage_dry_run),
            ("执行移入重复复核区", self.stage_confirm_disabled),
            ("打开详细报告", self.open_report),
        ]:
            b = QPushButton(text)
            b.clicked.connect(cb)
            buttons.addWidget(b)
            if text == "执行移入重复复核区":
                b.setEnabled(False)
                b.setToolTip("重复文件的真实归档需要命令行确认，GUI 当前只提供预览。")
        layout.addLayout(buttons)
        self.empty = QLabel("")
        layout.addWidget(self.empty)
        body = QHBoxLayout()
        self.group_list = QListWidget()
        self.group_list.itemSelectionChanged.connect(self._selection_changed)
        body.addWidget(self.group_list, 1)
        self.member_table = QTableWidget(0, 8)
        self.member_table.setHorizontalHeaderLabels(["文件名", "区域", "质量分", "质量等级", "章节数", "字数", "标签", "推荐角色"])
        body.addWidget(self.member_table, 2)
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.addWidget(QLabel("当前组解释"))
        self.detail = QTextEdit("请选择一个重复/版本组。")
        self.detail.setReadOnly(True)
        right_layout.addWidget(self.detail)
        for text, cb in [
            ("打开选中文件", self.open_selected_file),
            ("打开所在文件夹", self.open_selected_dir),
            ("忽略本组", lambda: self.detail.append("\n已在界面中忽略本组；不会修改任何文件。")),
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
        self.report_path = find_latest_report(self.repo, "duplicate")
        data = load_duplicate_report(self.report_path)
        self.groups = data.get("groups", [])
        self.group_list.clear()
        for index, group in enumerate(self.groups):
            name = group.get("title_norm") or group.get("title") or f"第 {index + 1} 组"
            members = len(group.get("members") or [])
            safe = self._is_exact_safe_group(group)
            text = f"{name}\n{group_type_label(group.get('group_type'))} · {members} 本 · {'可预览处理' if safe else '需要人工确认'}"
            item = QListWidgetItem(text)
            item.setData(32, index)
            self.group_list.addItem(item)
        self.empty.setText("还没有重复检测结果。点击“运行精确去重”或“运行近似去重”开始分析。" if not self.groups else "")
        if self.groups:
            self.group_list.setCurrentRow(0)

    def _is_exact_safe_group(self, group: dict) -> bool:
        return group.get("group_type") in {"exact_duplicate", "duplicate"} and "possible_update_version" not in (group.get("risk_flags") or [])

    def select_safe_groups(self) -> None:
        count = sum(1 for group in self.groups if self._is_exact_safe_group(group))
        self.detail.setPlainText(
            f"已识别 {count} 个可预览处理的精确重复组。\n"
            "近似重复、同书不同版本和可能是新版的项目继续要求人工确认。\n"
            "重复文件的真实归档需要命令行确认，GUI 当前只提供预览。"
        )

    def selected_group(self) -> dict | None:
        item = self.group_list.currentItem()
        if not item:
            return None
        index = item.data(32)
        return self.groups[index] if 0 <= index < len(self.groups) else None

    def selected_member_book(self) -> dict | None:
        group = self.selected_group()
        row = self.member_table.currentRow()
        members = group.get("members", []) if group else []
        if 0 <= row < len(members):
            return members[row].get("book") or members[row]
        return None

    def _selection_changed(self) -> None:
        group = self.selected_group()
        members = group.get("members", []) if group else []
        self.member_table.setRowCount(len(members))
        for r, member in enumerate(members):
            book = member.get("book") or member
            values = [book.get("file_name"), area_label(book.get("repo_area")), book.get("quality_score"), quality_label(book.get("quality_level")), book.get("chapter_count"), book.get("char_count_clean"), book.get("tags") or "", action_label(member.get("suggested_role") or member.get("role"))]
            for c, value in enumerate(values):
                self.member_table.setItem(r, c, QTableWidgetItem(str(value or "")))
        if not group:
            self.detail.setPlainText("请选择一个重复/版本组。")
            return
        self.detail.setPlainText(
            "\n".join(
                [
                    f"推荐保留：{group.get('recommended_keep_book_id') or '需要人工确认'}",
                    f"推荐原因：{group.get('reason_summary') or group.get('reason') or '根据区域、质量、章节和字数综合判断。'}",
                    f"可能是新版：{'是' if 'possible_update_version' in (group.get('risk_flags') or []) else '否'}",
                    f"作者冲突：{'是' if 'author_conflict' in (group.get('risk_flags') or []) else '否'}",
                    f"风险提示：{risks_label(group.get('risk_flags')) or '未发现明显风险'}",
                    "安全说明：本页面不会永久删除文件；GUI 当前只提供移入重复复核区的预览。",
                ]
            )
        )

    def open_selected_file(self) -> None:
        if book := self.selected_member_book():
            open_file(book.get("current_path") or "")

    def open_selected_dir(self) -> None:
        if book := self.selected_member_book():
            open_parent_folder(book.get("current_path") or "")

    def open_report(self) -> None:
        if self.report_path:
            html = Path(str(self.report_path)).with_suffix(".html")
            open_in_system(html if html.exists() else self.report_path)

    def open_dir(self) -> None:
        if self.report_path:
            open_in_system(Path(str(self.report_path)).parent)

    def stage_dry_run(self) -> None:
        if self.report_path:
            self.run_command("stage-duplicates", ["--report", str(self.report_path), "--dry-run"])

    def stage_confirm_disabled(self) -> None:
        self.detail.setPlainText("重复文件的真实归档需要命令行确认，GUI 当前只提供预览。")
