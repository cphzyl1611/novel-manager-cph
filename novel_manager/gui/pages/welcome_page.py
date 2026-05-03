from __future__ import annotations

from PySide6.QtWidgets import QDialog, QFileDialog, QHBoxLayout, QLabel, QMessageBox, QPushButton, QVBoxLayout

from ..repo_state import detect_plain_txt_folder, get_repo_structure_status, import_txt_folder_to_library


class WelcomeDialog(QDialog):  # pragma: no cover
    def __init__(self, run_init, set_repo, parent=None):
        super().__init__(parent)
        self.run_init = run_init
        self.set_repo = set_repo
        self.setWindowTitle("欢迎使用 novel_repo_manager")
        self.resize(760, 300)
        layout = QVBoxLayout(self)
        title = QLabel("请选择开始方式")
        title.setObjectName("CardValue")
        layout.addWidget(title)
        buttons = QHBoxLayout()
        for text, desc, handler in [
            ("新建小说仓库", "适合第一次使用，会创建 library、incoming、reports、db、logs 等目录。", self.new_repo),
            ("打开已有仓库", "选择已经初始化过的 NovelRepo 根目录。", self.open_repo),
            ("导入普通 TXT 文件夹", "复制 TXT 到仓库 library，不移动、不删除原文件。", self.import_folder),
        ]:
            button = QPushButton(f"{text}\n\n{desc}")
            button.setMinimumHeight(140)
            button.clicked.connect(handler)
            buttons.addWidget(button)
        layout.addLayout(buttons)

    def new_repo(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "选择或创建仓库目录")
        if path:
            self.run_init(path)
            self.set_repo(path)
            self.accept()

    def open_repo(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "选择已初始化仓库")
        if not path:
            return
        status = get_repo_structure_status(path)
        if not status["initialized"]:
            QMessageBox.warning(self, "目录不完整", "该目录不像一个已初始化仓库。可以改为新建仓库，或选择其他目录。")
            return
        self.set_repo(path)
        self.accept()

    def import_folder(self) -> None:
        source = QFileDialog.getExistingDirectory(self, "选择普通 TXT 文件夹")
        if not source:
            return
        info = detect_plain_txt_folder(source)
        if not info["is_plain_txt_folder"]:
            QMessageBox.information(self, "未发现 TXT", "该目录不像普通 TXT 小说文件夹。")
            return
        repo = QFileDialog.getExistingDirectory(self, "选择目标 NovelRepo 仓库")
        if not repo:
            return
        status = get_repo_structure_status(repo)
        if not status["initialized"]:
            QMessageBox.warning(self, "目标仓库无效", "目标目录不是已初始化仓库。")
            return
        dry = import_txt_folder_to_library(source, repo, dry_run=True)
        ok = QMessageBox.question(self, "复制预览", f"发现 {dry['found_count']} 个 TXT。是否复制到 library？")
        if ok == QMessageBox.Yes:
            result = import_txt_folder_to_library(source, repo, dry_run=False, apply=True)
            QMessageBox.information(self, "复制完成", f"已复制 {result['copied_count']} 个 TXT。请运行扫描。")
            self.set_repo(repo)
            self.accept()
