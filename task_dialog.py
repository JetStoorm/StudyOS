"""Форма создания и редактирования задачи с проверкой перед сохранением."""

from pathlib import Path

from PyQt6 import uic
from PyQt6.QtWidgets import QDialog, QMessageBox

from database import Database


class TaskDialog(QDialog):
    """Общий диалог задачи: поля заполняет MainWindow, ввод проверяет сам диалог."""

    def __init__(self, parent=None):
        """Загружает форму Qt Designer и связывает галочку срока с доступностью даты.

        parent — родительское окно Qt, которому принадлежит диалог.
        """
        super().__init__(parent)
        ui_path = Path(__file__).resolve().parent / "ui" / "task_dialog.ui"
        uic.loadUi(str(ui_path), self)
        self.taskHasDeadlineCheck.toggled.connect(self.taskDeadlineEdit.setEnabled)
        self.taskDeadlineEdit.setEnabled(self.taskHasDeadlineCheck.isChecked())

    def accept(self):
        """Проверяет название и длительность перед подтверждением формы.

        Переопределяет QDialog.accept: при ошибке форма остаётся открытой,
        введённые значения сохраняются, а фокус возвращается к проблемному полю.
        """
        if not self.taskTitleEdit.text().strip():
            QMessageBox.warning(self, "Ошибка", "Введите название задачи.")
            self.taskTitleEdit.setFocus()
            return
        try:
            Database.validate_duration(self.taskDurationSpin.value())
        except ValueError as error:
            QMessageBox.warning(self, "Ошибка", str(error))
            self.taskDurationSpin.setFocus()
            return
        # Только успешная проверка выставляет Accepted и закрывает диалог.
        super().accept()
