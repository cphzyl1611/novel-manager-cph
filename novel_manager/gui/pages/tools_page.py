from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QCheckBox, QComboBox, QFileDialog, QFormLayout, QHBoxLayout, QLineEdit, QMessageBox, QPushButton, QPlainTextEdit, QVBoxLayout, QWidget

from ..i18n import AREA_LABELS


class ToolsPage(QWidget):  # pragma: no cover
    def __init__(self, run_command, stop_command, parent=None):
        super().__init__(parent)
        self.run_command = run_command
        self.stop_command = stop_command
        layout = QVBoxLayout(self)
        from PySide6.QtWidgets import QLabel
        layout.addWidget(QLabel("高级工具 / 命令执行：普通整理流程建议使用左侧的重复处理、更新处理、重命名计划等页面。"))
        form = QFormLayout()
        self.command = QComboBox()
        self.command.addItems([
            "scan",
            "quality-report",
            "find-duplicates exact",
            "find-duplicates near",
            "diagnose-near",
            "group-books",
            "check-updates",
            "auto-tag dry-run",
            "auto-tag apply",
            "rename-plan",
            "refresh-metadata dry-run",
            "post-rename-check",
            "summary-report",
            "report-index",
            "apply-renames dry-run",
            "apply-updates dry-run",
            "stage-duplicates dry-run",
        ])
        self.area = QComboBox()
        for value in ["library", "incoming", "all", "archive", "review_duplicates"]:
            self.area.addItem(AREA_LABELS[value], value)
        self.query = QLineEdit()
        self.limit = QLineEdit()
        self.limit.setPlaceholderText("100")
        self.include_rejected = QCheckBox("include-rejected")
        self.include_low = QCheckBox("include-low-confidence")
        self.min_score = QLineEdit()
        self.min_score.setPlaceholderText("0.82")
        report_row = QHBoxLayout()
        self.report = QLineEdit()
        browse = QPushButton("选择报告")
        browse.clicked.connect(self._browse_report)
        report_row.addWidget(self.report)
        report_row.addWidget(browse)
        form.addRow("操作名称", self.command)
        form.addRow("区域", self.area)
        form.addRow("关键词", self.query)
        form.addRow("数量限制", self.limit)
        form.addRow("最低相似度", self.min_score)
        self.include_rejected.setText("包含已拒绝项")
        self.include_low.setText("包含低置信候选")
        form.addRow("", self.include_rejected)
        form.addRow("", self.include_low)
        form.addRow("报告文件", report_row)
        layout.addLayout(form)
        buttons = QHBoxLayout()
        run = QPushButton("执行")
        run.clicked.connect(self.execute)
        stop = QPushButton("停止")
        stop.clicked.connect(self.stop_command)
        clear = QPushButton("清空日志")
        clear.clicked.connect(lambda: self.log.clear())
        buttons.addWidget(run)
        buttons.addWidget(stop)
        buttons.addWidget(clear)
        layout.addLayout(buttons)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        layout.addWidget(self.log)

    def append_log(self, text: str) -> None:
        self.log.appendPlainText(text.rstrip())

    def _browse_report(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "选择报告 JSON", "", "JSON (*.json);;All Files (*)")
        if path:
            self.report.setText(path)

    def execute(self) -> None:
        label = self.command.currentText()
        args: list[str] = []
        if label.startswith("scan"):
            command = "scan"
            args = ["--area", self.area.currentData()]
        elif label == "quality-report":
            command = "quality-report"
            args = ["--area", "all"]
        elif label == "find-duplicates exact":
            command = "find-duplicates"
            args = ["--mode", "exact", "--area", "all"]
        elif label == "find-duplicates near":
            command = "find-duplicates"
            args = ["--mode", "near", "--area", "all"]
            if self.include_low.isChecked():
                args.append("--include-low-confidence")
            if self.min_score.text().strip():
                args.extend(["--min-score", self.min_score.text().strip()])
        elif label == "diagnose-near":
            command = "diagnose-near"
            args = ["--area", "all"]
        elif label == "group-books":
            command = "group-books"
        elif label == "check-updates":
            command = "check-updates"
            if self.include_rejected.isChecked():
                args.append("--include-rejected")
        elif label == "auto-tag dry-run":
            command = "auto-tag"
            args = ["--dry-run"]
        elif label == "auto-tag apply":
            command = "auto-tag"
            args = ["--apply"]
        elif label == "rename-plan":
            command = "rename-plan"
        elif label == "refresh-metadata dry-run":
            command = "refresh-metadata"
            args = ["--area", self.area.currentData(), "--dry-run"]
        elif label == "post-rename-check":
            command = "post-rename-check"
        elif label == "summary-report":
            command = "summary-report"
        elif label == "report-index":
            command = "report-index"
        elif label == "apply-renames dry-run":
            command = "apply-renames"
            report_path = self.report.text().strip()
            if not report_path:
                QMessageBox.warning(self, "缺少报告文件", "请先选择报告文件。")
                return
            if not Path(report_path).exists():
                QMessageBox.warning(self, "报告文件不存在", f"报告文件不存在：{report_path}")
                return
            args = ["--report", report_path, "--dry-run"]
        elif label == "apply-updates dry-run":
            command = "apply-updates"
            report_path = self.report.text().strip()
            if not report_path:
                QMessageBox.warning(self, "缺少报告文件", "请先选择报告文件。")
                return
            if not Path(report_path).exists():
                QMessageBox.warning(self, "报告文件不存在", f"报告文件不存在：{report_path}")
                return
            args = ["--report", report_path, "--dry-run"]
        else:
            command = "stage-duplicates"
            report_path = self.report.text().strip()
            if not report_path:
                QMessageBox.warning(self, "缺少报告文件", "请先选择报告文件。")
                return
            if not Path(report_path).exists():
                QMessageBox.warning(self, "报告文件不存在", f"报告文件不存在：{report_path}")
                return
            args = ["--report", report_path, "--dry-run"]
        if self.query.text().strip() and command in {"diagnose-near", "check-updates", "rename-plan", "refresh-metadata"}:
            args.extend(["--query", self.query.text().strip()])
        if self.limit.text().strip() and command not in {"quality-report", "summary-report", "report-index", "post-rename-check"}:
            args.extend(["--limit", self.limit.text().strip()])
        if command == "auto-tag" and "--apply" in args:
            text = (
                "将根据质量、文件名和章节信息自动添加标签。不会移动或删除文件。\n\n"
                "安全说明：\n"
                "- 不会永久删除文件\n"
                "- 不会覆盖已有文件\n"
                "- 不会修改 TXT 内容\n"
                "- 操作会写入日志"
            )
            if QMessageBox.question(self, "应用自动标签", text) != QMessageBox.Yes:
                return
            self.run_command(command, args, safe_action="apply_auto_tags")
        else:
            self.run_command(command, args)
