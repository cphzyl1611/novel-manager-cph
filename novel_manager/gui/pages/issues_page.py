from __future__ import annotations

from PySide6.QtWidgets import QFrame, QGridLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from ..report_loaders import collect_issue_summary


class IssueCard(QFrame):  # pragma: no cover
    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.setObjectName("Panel")
        layout = QVBoxLayout(self)
        self.title = QLabel(title)
        self.title.setObjectName("CardTitle")
        self.value = QLabel("0")
        self.value.setObjectName("CardValue")
        self.detail = QLabel("")
        self.detail.setWordWrap(True)
        layout.addWidget(self.title)
        layout.addWidget(self.value)
        layout.addWidget(self.detail)

    def set_content(self, value: int, detail: str) -> None:
        self.value.setText(str(value))
        self.detail.setText(detail)


class IssuesPage(QWidget):  # pragma: no cover
    def __init__(self, go_to_page=None, parent=None):
        super().__init__(parent)
        self.go_to_page = go_to_page
        layout = QVBoxLayout(self)
        header = QLabel("待处理事项会汇总最近报告和小说库数据，优先引导你处理可安全执行的项目。")
        header.setWordWrap(True)
        layout.addWidget(header)
        grid = QGridLayout()
        self.cards = {
            "duplicate": IssueCard("重复与版本问题"),
            "update": IssueCard("更新候选"),
            "rename": IssueCard("文件名问题"),
            "health": IssueCard("健康检查问题"),
            "quality": IssueCard("质量问题"),
        }
        self.buttons: dict[str, QPushButton] = {}
        for index, (key, card) in enumerate(self.cards.items()):
            wrapper = QWidget()
            inner = QVBoxLayout(wrapper)
            inner.addWidget(card)
            button = QPushButton("查看")
            button.clicked.connect(lambda _=False, k=key: self._go(k))
            self.buttons[key] = button
            inner.addWidget(button)
            grid.addWidget(wrapper, index // 2, index % 2)
        layout.addLayout(grid)
        self.empty = QLabel("")
        self.empty.setWordWrap(True)
        layout.addWidget(self.empty)
        layout.addStretch()

    def refresh(self, repo: str | None = None) -> None:
        data = collect_issue_summary(repo)
        dup = data["duplicate"]
        self.cards["duplicate"].set_content(
            dup["exact"] + dup["near"] + dup["same_work"],
            f"精确重复 {dup['exact']} 组，近似重复 {dup['near']} 组，同书版本 {dup['same_work']} 组。",
        )
        self.buttons["duplicate"].setText("预览移入重复复核区" if dup["exact"] else "需要人工确认")
        upd = data["update"]
        self.cards["update"].set_content(
            upd["incoming"] + upd["recommended"] + upd["review"],
            f"新下载区 {upd['incoming']} 本；可安全更新 {upd.get('safe', 0)} 个，需要复核 {upd['review']} 个。",
        )
        self.buttons["update"].setText("执行推荐更新" if upd.get("safe", 0) else "暂无可安全更新项")
        ren = data["rename"]
        self.cards["rename"].set_content(
            ren["recommended"] + ren["manual_review"] + ren["conflict"],
            f"可安全改名 {ren.get('safe', 0)} 条，需要确认 {ren['manual_review']} 条，冲突 {ren['conflict']} 条。",
        )
        self.buttons["rename"].setText("一键处理安全改名" if ren.get("safe", 0) else "查看文件名整理")
        hea = data["health"]
        self.cards["health"].set_content(
            hea["errors"] + hea["warnings"],
            f"错误 {hea['errors']} 个，警告 {hea['warnings']} 个；标题噪声 {hea['dirty_title_norm']} 个。",
        )
        self.buttons["health"].setText("刷新元数据" if hea["dirty_title_norm"] else "查看健康检查")
        qua = data["quality"]
        self.cards["quality"].set_content(
            qua["mojibake"] + qua["missing_chapter"] + qua["many_ads"] + qua["low_quality"],
            f"疑似乱码 {qua['mojibake']} 本，疑似缺章 {qua['missing_chapter']} 本，广告较多 {qua['many_ads']} 本，低质量 {qua['low_quality']} 本。",
        )
        self.buttons["quality"].setText("查看问题小说")
        self.empty.setText("暂无待处理事项。可以先扫描小说库或生成相关报告。" if not data["has_data"] else "")

    def _go(self, key: str) -> None:
        if not self.go_to_page:
            return
        self.go_to_page(
            {
                "duplicate": "重复与版本",
                "update": "更新候选",
                "rename": "文件名整理",
                "health": "健康检查",
                "quality": "小说库",
            }[key]
        )
