from __future__ import annotations

from PySide6.QtWidgets import QCheckBox, QComboBox, QFormLayout, QGroupBox, QLineEdit, QPushButton, QSpinBox, QVBoxLayout, QWidget

from ..command_runner import default_python
from ..repo_state import load_gui_settings, save_gui_settings


class SettingsPage(QWidget):  # pragma: no cover
    def __init__(self, parent=None):
        super().__init__(parent)
        self.settings = load_gui_settings()
        layout = QVBoxLayout(self)
        basic = QGroupBox("基础设置")
        form = QFormLayout(basic)
        self.repo_path = QLineEdit(self.settings.get("last_repo_path", ""))
        self.default_area = QComboBox()
        for text, value in [("小说库", "library"), ("新下载区", "incoming"), ("全部", "all")]:
            self.default_area.addItem(text, value)
        self.default_area.setCurrentIndex(max(0, self.default_area.findData(self.settings.get("default_area", "library"))))
        self.naming_style = QComboBox()
        for text, value in [("书名 - 作者 [状态]", "title-author-status"), ("书名 - 作者", "title-author"), ("书名", "title-only")]:
            self.naming_style.addItem(text, value)
        self.naming_style.setCurrentIndex(max(0, self.naming_style.findData(self.settings.get("naming_style", "title-author-status"))))
        self.page_size = QSpinBox()
        self.page_size.setRange(20, 1000)
        self.page_size.setValue(int(self.settings.get("page_size", 200)))
        self.theme = QLineEdit("浅色")
        self.theme.setReadOnly(True)
        form.addRow("当前仓库路径", self.repo_path)
        form.addRow("默认管理区域", self.default_area)
        form.addRow("默认命名格式", self.naming_style)
        form.addRow("每页显示数量", self.page_size)
        form.addRow("主题", self.theme)
        layout.addWidget(basic)

        self.advanced = QGroupBox("高级设置")
        self.advanced.setCheckable(True)
        self.advanced.setChecked(False)
        adv = QFormLayout(self.advanced)
        self.python_path = QLineEdit(self.settings.get("python_path", default_python()))
        self.show_commands = QCheckBox("显示底层命令")
        self.show_commands.setChecked(bool(self.settings.get("show_commands", False)))
        self.debug = QCheckBox("调试模式")
        self.debug.setChecked(bool(self.settings.get("debug", False)))
        adv.addRow("Python 命令路径", self.python_path)
        adv.addRow(self.show_commands)
        adv.addRow(self.debug)
        layout.addWidget(self.advanced)

        save = QPushButton("保存设置")
        save.clicked.connect(self.save)
        layout.addWidget(save)
        layout.addStretch()

    def save(self) -> None:
        self.settings.update(
            {
                "last_repo_path": self.repo_path.text().strip(),
                "default_area": self.default_area.currentData(),
                "naming_style": self.naming_style.currentData(),
                "page_size": self.page_size.value(),
                "python_path": self.python_path.text().strip() or default_python(),
                "show_commands": self.show_commands.isChecked(),
                "debug": self.debug.isChecked(),
            }
        )
        save_gui_settings(self.settings)
