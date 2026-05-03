from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtWidgets import QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget

from ..report_loaders import collect_issue_summary, find_latest_report, load_health_report, summarize_report
from ..repo_state import get_repo_structure_status, load_dashboard_stats, load_recent_operations
from ..widgets import StatCard, make_primary_button


class DashboardPage(QWidget):  # pragma: no cover
    def __init__(self, run_command, go_to_page=None, parent=None):
        super().__init__(parent)
        self.run_command = run_command
        self.go_to_page = go_to_page
        layout = QVBoxLayout(self)
        self.status = QFrame()
        self.status.setObjectName("Panel")
        status_layout = QGridLayout(self.status)
        self.repo_path = QLabel("未选择仓库")
        self.scan_state = QLabel("未扫描")
        self.health_state = QLabel("暂无健康检查")
        self.last_time = QLabel("暂无整理记录")
        self.total_books = StatCard("小说总数", "0")
        status_layout.addWidget(QLabel("当前仓库"), 0, 0)
        status_layout.addWidget(self.repo_path, 0, 1, 1, 3)
        status_layout.addWidget(self.total_books, 1, 0)
        status_layout.addWidget(self.scan_state, 1, 1)
        status_layout.addWidget(self.health_state, 1, 2)
        status_layout.addWidget(self.last_time, 1, 3)
        layout.addWidget(self.status)

        self.steps = QTableWidget(5, 4)
        self.steps.setHorizontalHeaderLabels(["整理步骤", "当前状态", "发现问题", "主操作"])
        self.steps.verticalHeader().setVisible(False)
        layout.addWidget(self.steps)

        self.safe_grid = QGridLayout()
        self.safe_cards = {
            "rename": StatCard("可安全改名", "0"),
            "update": StatCard("可安全更新", "0"),
            "tag": StatCard("可自动标签", "待预览"),
            "duplicate": StatCard("重复归档", "需确认"),
        }
        for index, card in enumerate(self.safe_cards.values()):
            self.safe_grid.addWidget(card, 0, index)
        layout.addLayout(self.safe_grid)

        button_row = QHBoxLayout()
        actions = [
            ("扫描小说", "scan", ["--area", "library"], None),
            ("查看待处理事项", None, [], "待处理事项"),
            ("一键整理安全文件名", None, [], "文件名整理"),
            ("检查新下载更新", "check-updates", [], None),
            ("查看重复与版本", None, [], "重复与版本"),
            ("运行健康检查", "post-rename-check", [], None),
        ]
        for text, command, args, page in actions:
            button = make_primary_button(text) if text == "查看待处理事项" else QPushButton(text)
            if command:
                button.clicked.connect(lambda _=False, c=command, a=args: self.run_command(c, a))
            else:
                button.clicked.connect(lambda _=False, p=page: self.go_to_page and self.go_to_page(p))
            button_row.addWidget(button)
        layout.addLayout(button_row)

        self.operations = QTableWidget(0, 1)
        self.operations.setHorizontalHeaderLabels(["最近操作"])
        layout.addWidget(self.operations)

    def refresh(self, repo: str | None) -> None:
        stats = load_dashboard_stats(repo) if repo else {}
        issues = collect_issue_summary(repo)
        self.repo_path.setText(str(repo or "未选择仓库"))
        self.total_books.set_value(stats.get("books", 0))
        if repo:
            self.scan_state.setText("已扫描" if stats.get("books", 0) else "尚未扫描到小说")
            self.health_state.setText(self._health_text(repo))
            self.last_time.setText(self._last_report_time(repo))
        else:
            self.scan_state.setText("请先选择仓库")
            self.health_state.setText("暂无健康检查")
            self.last_time.setText("暂无整理记录")
        self._populate_steps(stats, issues)
        self.safe_cards["rename"].set_value(issues["rename"].get("safe", issues["rename"].get("recommended", 0)))
        self.safe_cards["update"].set_value(issues["update"].get("safe", issues["update"].get("recommended", 0)))
        ops = load_recent_operations(repo, limit=8) if repo else []
        self.operations.setRowCount(max(len(ops), 1))
        if ops:
            for row, line in enumerate(ops):
                self.operations.setItem(row, 0, QTableWidgetItem(line))
        else:
            self.operations.setItem(0, 0, QTableWidgetItem("暂无操作记录。"))

    def _populate_steps(self, stats: dict, issues: dict) -> None:
        rows = [
            ("① 导入 / 扫描小说", "已扫描" if stats.get("books", 0) else "待扫描", stats.get("books", 0), "扫描小说"),
            ("② 处理重复与版本", "需要处理" if sum(issues["duplicate"].values()) else "暂无问题", sum(issues["duplicate"].values()), "查看重复与版本"),
            ("③ 检查新下载更新", "需要检查" if issues["update"]["incoming"] else "暂无新下载", issues["update"]["incoming"], "检查新下载更新"),
            ("④ 整理文件名", "有安全项" if issues["rename"].get("safe", 0) else "暂无安全项", issues["rename"].get("safe", 0), "一键整理安全文件名"),
            ("⑤ 健康检查与完成", "有警告" if issues["health"]["warnings"] else "可检查", issues["health"]["errors"] + issues["health"]["warnings"], "运行健康检查"),
        ]
        for r, row in enumerate(rows):
            for c, value in enumerate(row):
                self.steps.setItem(r, c, QTableWidgetItem(str(value)))

    def _health_text(self, repo: str) -> str:
        path = find_latest_report(repo, "health")
        stats = summarize_report(load_health_report(path))
        if not path:
            return "未运行健康检查"
        return f"健康检查：{stats.get('errors', 0)} 错误，{stats.get('warnings', 0)} 警告"

    def _last_report_time(self, repo: str) -> str:
        candidates = [p for key in ["duplicate", "rename", "update", "health"] if (p := find_latest_report(repo, key))]
        if not candidates:
            return "暂无整理记录"
        latest = max(candidates, key=lambda p: p.stat().st_mtime)
        return "最近整理：" + datetime.fromtimestamp(Path(latest).stat().st_mtime).strftime("%Y-%m-%d %H:%M")
