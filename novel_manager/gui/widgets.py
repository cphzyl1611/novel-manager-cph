from __future__ import annotations

try:
    from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout
except ImportError:  # pragma: no cover
    QFrame = object  # type: ignore
    QLabel = object  # type: ignore
    QPushButton = object  # type: ignore
    QVBoxLayout = object  # type: ignore
    QHBoxLayout = object  # type: ignore


class StatCard(QFrame):  # pragma: no cover - GUI widget
    def __init__(self, title: str, value: str = "0", parent=None):
        super().__init__(parent)
        self.setObjectName("StatCard")
        layout = QVBoxLayout(self)
        self.title_label = QLabel(title)
        self.title_label.setObjectName("CardTitle")
        self.value_label = QLabel(value)
        self.value_label.setObjectName("CardValue")
        layout.addWidget(self.title_label)
        layout.addWidget(self.value_label)

    def set_value(self, value: object) -> None:
        self.value_label.setText(str(value))


def make_primary_button(text: str) -> QPushButton:  # pragma: no cover
    button = QPushButton(text)
    button.setProperty("class", "primary")
    return button
