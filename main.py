"""Главное окно StudyOS: действия пользователя, таблицы и запуск планировщика.

Данные читаются и сохраняются через Database, а расписание рассчитывается
независимым модулем scheduler. Формы интерфейса загружаются из файлов Qt Designer.
"""

import sys
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path

from PyQt6 import uic
from PyQt6.QtCore import Qt, QDate, QTime, QTimer
from PyQt6.QtGui import QAction, QColor
from PyQt6.QtWidgets import QApplication, QMainWindow, QInputDialog, QLineEdit, QListWidgetItem, QMessageBox, \
    QHeaderView, QDialog, QTableWidgetItem, QFileDialog

from database import Database
from task_dialog import TaskDialog
import csv
from file_exchange import import_tasks_csv, export_tasks_csv, export_schedule_csv, export_report_txt

from scheduler import Task, FreeSlot, generate_schedule


class MainWindow(QMainWindow):
    """Объединяет вкладки предметов, задач, расписания и статистики."""

    def __init__(self, db_path=None):
        """Загружает форму, открывает базу и подключает сигналы виджетов.

        db_path — путь к SQLite; None выбирает пользовательский каталог,
        а ':memory:' позволяет открыть окно с временной базой в памяти.
        """
        super().__init__()

        ui_path = Path(__file__).resolve().parent / "ui" / "main_window.ui"
        uic.loadUi(str(ui_path), self)
        self.tasksTableWidget.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch)
        self.scheduleTableWidget.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch)
        self.editTaskButton.clicked.connect(self.edit_task)
        self.deleteTaskButton.clicked.connect(self.delete_task)
        self.completeTaskButton.clicked.connect(self.complete_task)

        self.db = Database(db_path)
        self.deadlinesTableWidget.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.setup_file_menu()

        self.addTaskButton.clicked.connect(self.add_task)
        self.load_tasks()

        # Подключаем кнопки к обработчикам.
        self.addSubjectButton.clicked.connect(self.add_subject)
        self.editSubjectButton.clicked.connect(self.edit_subject)
        self.deleteSubjectButton.clicked.connect(self.delete_subject)

        # Поиск обновляется при каждом изменении текста.
        self.subjectSearchEdit.textChanged.connect(
            self.load_subjects
        )

        self.load_subjects()

        self.plannerStartDateEdit.setDate(QDate.currentDate())
        self.plannerDaysSpin.setValue(7)

        self.plannerStartTimeEdit.setTime(QTime(17, 0))
        self.plannerEndTimeEdit.setTime(QTime(19, 0))

        self.generateScheduleButton.clicked.connect(
            self.generate_plan
        )

        self.load_schedule()

        self.tabWidget.currentChanged.connect(self.refresh_dashboard)
        # Время и сроки меняются даже без действий пользователя: обновляем обзор раз в минуту.
        self.dashboardTimer = QTimer(self)
        self.dashboardTimer.timeout.connect(self.refresh_dashboard)
        self.dashboardTimer.start(60_000)
        self.statusbar.showMessage(f"База данных: {self.db.path}")

    def setup_file_menu(self):
        """Создаёт меню «Файл» и связывает его действия с импортом и экспортом."""
        menu = self.menubar.addMenu("Файл")
        actions = (
            ("Импорт задач из CSV…", self.import_csv),
            ("Экспорт задач в CSV…", self.export_tasks),
            ("Экспорт расписания в CSV…", self.export_schedule),
            ("Сохранить отчёт TXT…", self.export_report),
        )
        for title, callback in actions:
            action = QAction(title, self)
            action.triggered.connect(callback)
            menu.addAction(action)

    def import_csv(self):
        """Открывает CSV, импортирует задачи и показывает число записей и дубликатов.

        Отмена выбора файла ничего не меняет. Ошибки чтения, проверки данных
        и SQLite отображаются в сообщении пользователю.
        """
        path, _ = QFileDialog.getOpenFileName(self, "Импорт задач", "", "CSV (*.csv)")
        if not path:
            return
        try:
            added, skipped = import_tasks_csv(self.db, path)
        except (OSError, UnicodeError, ValueError, csv.Error, sqlite3.Error) as error:
            QMessageBox.warning(self, "Ошибка импорта", str(error))
            return
        self.load_subjects()
        self.load_tasks()
        QMessageBox.information(
            self, "Импорт завершён",
            f"Добавлено задач: {added}. Точных дубликатов пропущено: {skipped}.\n"
            "Для новых активных задач составьте расписание."
        )

    def save_export(self, title, filename, file_filter, exporter):
        """Выбирает путь сохранения и вызывает переданную функцию экспорта.

        title — заголовок диалога, filename — предлагаемое имя файла,
        file_filter — фильтр расширений Qt; exporter вызывается как exporter(db, path).
        """
        path, _ = QFileDialog.getSaveFileName(self, title, filename, file_filter)
        if not path:
            return
        if not Path(path).suffix:
            path += Path(filename).suffix
        try:
            exporter(self.db, path)
        except (OSError, UnicodeError, ValueError, csv.Error, sqlite3.Error) as error:
            QMessageBox.warning(self, "Ошибка экспорта", str(error))
            return
        QMessageBox.information(self, "Экспорт завершён", f"Файл сохранён:\n{path}")

    def export_tasks(self):
        """Предлагает сохранить задачи всех статусов в CSV."""
        self.save_export("Экспорт задач", "studyos_tasks.csv", "CSV (*.csv)", export_tasks_csv)

    def export_schedule(self):
        """Предлагает сохранить текущее расписание в CSV."""
        self.save_export("Экспорт расписания", "studyos_schedule.csv", "CSV (*.csv)", export_schedule_csv)

    def export_report(self):
        """Предлагает сохранить статистику, задачи и расписание в отчёт TXT."""
        self.save_export("Отчёт об обучении", "studyos_report.txt", "Текст (*.txt)", export_report_txt)

    def refresh_dashboard(self, _index=None):
        """Обновляет счётчики, прогресс, нагрузку и таблицу ближайших сроков.

        _index принимается для совместимости с сигналом переключения вкладок;
        само значение индекса для расчёта статистики не требуется.
        """
        stats = self.db.get_statistics()
        self.activeCountLabel.setText(str(stats["active"]))
        self.completedCountLabel.setText(str(stats["completed"]))
        self.overdueCountLabel.setText(str(stats["overdue"]))
        self.completionProgressBar.setValue(stats["completion_percent"])
        self.workloadLabel.setText(
            f"Оставшаяся работа: {stats['remaining_minutes']} мин · "
            f"Запланировано: {stats['planned_minutes']} мин"
        )
        rows = self.db.get_upcoming_deadlines()
        self.deadlinesTableWidget.setRowCount(len(rows))
        for row, (title, subject, deadline, minutes) in enumerate(rows):
            values = (title, subject, date.fromisoformat(deadline).strftime("%d.%m.%Y"), f"{minutes} мин")
            for column, value in enumerate(values):
                self.deadlinesTableWidget.setItem(row, column, QTableWidgetItem(value))
        self.deadlinesTitleLabel.setText(
            "Ближайшие сроки · 5 активных задач, начиная с сегодня" if rows
            else "Ближайших сроков нет"
        )

    def load_subjects(self, _text=""):
        """Заполняет список предметов с учётом поиска без различия регистра.

        _text — аргумент сигнала textChanged; актуальная строка читается из поля поиска.
        """
        search = self.subjectSearchEdit.text().casefold()

        self.subjectsListWidget.clear()

        for subject_id, name in self.db.get_subjects():
            if search in name.casefold():
                item = QListWidgetItem(name)

                # Храним ID записи отдельно от её названия.
                item.setData(
                    Qt.ItemDataRole.UserRole,
                    subject_id
                )

                self.subjectsListWidget.addItem(item)

    def add_subject(self):
        """Запрашивает название предмета и сохраняет его, проверяя пустоту и дубликаты."""
        name, ok = QInputDialog.getText(
            self,
            "Новый предмет",
            "Название предмета:"
        )

        if not ok:
            return

        name = name.strip()

        if not name:
            QMessageBox.warning(
                self,
                "Ошибка",
                "Название предмета не может быть пустым."
            )
            return

        try:
            self.db.add_subject(name)
        except sqlite3.IntegrityError:
            QMessageBox.warning(
                self,
                "Ошибка",
                "Предмет с таким названием уже существует."
            )
            return

        self.subjectSearchEdit.clear()
        self.load_subjects()

    def edit_subject(self):
        """Переименовывает выбранный предмет и обновляет его название в таблице задач."""
        item = self.subjectsListWidget.currentItem()

        if item is None:
            QMessageBox.warning(
                self,
                "Ошибка",
                "Сначала выбери предмет."
            )
            return

        subject_id = item.data(Qt.ItemDataRole.UserRole)

        new_name, ok = QInputDialog.getText(
            self,
            "Изменить предмет",
            "Новое название:",
            QLineEdit.EchoMode.Normal,
            item.text()
        )

        if not ok or not new_name.strip():
            return

        try:
            self.db.update_subject(subject_id, new_name.strip())
        except sqlite3.IntegrityError:
            QMessageBox.warning(
                self,
                "Ошибка",
                "Предмет с таким названием уже существует."
            )
            return

        self.load_subjects()

        self.load_tasks()

    def delete_subject(self):
        """Удаляет выбранный предмет после подтверждения, если на него нет ссылок задач."""
        item = self.subjectsListWidget.currentItem()

        if item is None:
            QMessageBox.warning(
                self,
                "Ошибка",
                "Сначала выбери предмет."
            )
            return

        answer = QMessageBox.question(
            self,
            "Удаление",
            f"Удалить предмет «{item.text()}»?",
            QMessageBox.StandardButton.Yes |
            QMessageBox.StandardButton.No
        )

        if answer == QMessageBox.StandardButton.Yes:
            subject_id = item.data(Qt.ItemDataRole.UserRole)
            try:
                self.db.delete_subject(subject_id)
            except sqlite3.IntegrityError:
                QMessageBox.warning(
                    self, "Удаление предмета",
                    "Нельзя удалить предмет, у которого есть задачи, "
                    "в том числе завершённые или удалённые."
                )
                return
            self.load_subjects()

    def closeEvent(self, event):
        """При закрытии окна останавливает таймер и освобождает соединение с SQLite."""
        self.dashboardTimer.stop()
        self.db.close()
        super().closeEvent(event)

    def add_task(self):
        """Открывает форму новой задачи и сохраняет её после подтверждения.

        Предметы загружаются из базы; без предметов создать задачу нельзя.
        Отключённый срок сохраняется как None, установленный — как ISO-дата.
        """
        # Получаем предметы из базы данных.
        subjects = self.db.get_subjects()

        if not subjects:
            QMessageBox.warning(
                self,
                "Ошибка",
                "Сначала создайте хотя бы один предмет."
            )
            return

        # Создаём диалог.
        dialog = TaskDialog(self)

        # Заполняем выпадающий список предметов.
        for subject_id, name in subjects:
            dialog.taskSubjectCombo.addItem(name, subject_id)

        # Устанавливаем текущую дату.
        dialog.taskDeadlineEdit.setDate(QDate.currentDate())

        # Открываем окно и проверяем результат.
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        # Получаем значения из полей.
        title = dialog.taskTitleEdit.text().strip()

        if not title:
            QMessageBox.warning(
                self,
                "Ошибка",
                "Введите название задачи."
            )
            return

        subject_id = dialog.taskSubjectCombo.currentData()
        priority = dialog.taskPrioritySpin.value()
        duration = dialog.taskDurationSpin.value()

        # Срок может отсутствовать.
        deadline = None

        if dialog.taskHasDeadlineCheck.isChecked():
            deadline = dialog.taskDeadlineEdit.date().toString(
                "yyyy-MM-dd"
            )

        # Сохраняем задачу.
        self.db.add_task(
            title,
            subject_id,
            priority,
            duration,
            deadline
        )

        # Обновляем таблицу.
        self.load_tasks()

    def load_tasks(self):
        """Показывает активные задачи, выделяет просроченные и обновляет статистику."""
        tasks = self.db.get_tasks()

        self.tasksTableWidget.setRowCount(len(tasks))

        for row, task in enumerate(tasks):
            task_id, title, subject, priority, duration, deadline = task

            values = [
                title,
                subject,
                str(priority),
                f"{duration} мин",
                deadline if deadline else "Без срока"
            ]

            for col, value in enumerate(values):
                item = QTableWidgetItem(value)

                if deadline and deadline < date.today().isoformat():
                    item.setForeground(QColor("#b34d22"))
                    item.setToolTip("Срок выполнения задачи истёк")

                if col == 0:
                    # ID в UserRole связывает строку с записью БД даже при одинаковых названиях.
                    item.setData(
                        Qt.ItemDataRole.UserRole,
                        task_id
                    )

                self.tasksTableWidget.setItem(row, col, item)
        self.refresh_dashboard()

    def edit_task(self):
        """Заполняет диалог данными выбранной задачи и сохраняет изменения.

        При изменении срока, приоритета или длительности база удаляет
        незакончившиеся блоки задачи; пользователю предлагается пересоставить план.
        """
        row = self.tasksTableWidget.currentRow()

        if row < 0:
            QMessageBox.warning(
                self,
                "Ошибка",
                "Сначала выберите задачу."
            )
            return

        item = self.tasksTableWidget.item(row, 0)
        task_id = item.data(Qt.ItemDataRole.UserRole)

        task = self.db.get_task(task_id)

        if task is None:
            QMessageBox.warning(
                self,
                "Ошибка",
                "Задача не найдена."
            )
            return

        _, title, subject_id, priority, duration, deadline = task

        # Загружаем существующую форму.
        dialog = TaskDialog(self)
        dialog.setWindowTitle("Изменить задачу")

        # Заполняем список предметов.
        for sid, name in self.db.get_subjects():
            dialog.taskSubjectCombo.addItem(name, sid)

        # Устанавливаем текущие значения.
        dialog.taskTitleEdit.setText(title)
        dialog.taskPrioritySpin.setValue(priority)
        dialog.taskDurationSpin.setValue(duration)

        index = dialog.taskSubjectCombo.findData(subject_id)

        if index >= 0:
            dialog.taskSubjectCombo.setCurrentIndex(index)

        # Восстанавливаем срок выполнения.
        dialog.taskHasDeadlineCheck.setChecked(
            deadline is not None
        )

        if deadline:
            dialog.taskDeadlineEdit.setDate(
                QDate.fromString(deadline, "yyyy-MM-dd")
            )
        else:
            dialog.taskDeadlineEdit.setDate(QDate.currentDate())

        # Ждём подтверждения пользователя.
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        new_title = dialog.taskTitleEdit.text().strip()

        if not new_title:
            QMessageBox.warning(
                self,
                "Ошибка",
                "Название задачи не может быть пустым."
            )
            return

        new_deadline = None

        if dialog.taskHasDeadlineCheck.isChecked():
            new_deadline = dialog.taskDeadlineEdit.date().toString(
                "yyyy-MM-dd"
            )

        # Обновляем данные.
        self.db.update_task(
            task_id,
            new_title,
            dialog.taskSubjectCombo.currentData(),
            dialog.taskPrioritySpin.value(),
            dialog.taskDurationSpin.value(),
            new_deadline
        )

        # Перезагружаем таблицу.
        self.load_tasks()
        self.load_schedule()
        if (priority, duration, deadline) != (
            dialog.taskPrioritySpin.value(), dialog.taskDurationSpin.value(), new_deadline
        ):
            QMessageBox.information(
                self, "Расписание",
                "Условия задачи изменились. Её будущие занятия удалены. "
                "Составьте расписание заново."
            )

    def delete_task(self):
        """После подтверждения помечает задачу удалённой и обновляет обе таблицы."""
        row = self.tasksTableWidget.currentRow()

        if row < 0:
            QMessageBox.warning(
                self,
                "Ошибка",
                "Сначала выберите задачу."
            )
            return

        item = self.tasksTableWidget.item(row, 0)
        task_id = item.data(Qt.ItemDataRole.UserRole)

        answer = QMessageBox.question(
            self,
            "Удаление задачи",
            f"Удалить задачу «{item.text()}»?",
            QMessageBox.StandardButton.Yes
            | QMessageBox.StandardButton.No
        )

        if answer != QMessageBox.StandardButton.Yes:
            return

        self.db.delete_task(task_id)
        self.load_tasks()
        self.load_schedule()

    def generate_plan(self):
        """Создаёт и сохраняет расписание по настройкам вкладки планирования.

        Получает активные задачи, формирует ежедневные свободные интервалы,
        исключает прошедшее время и вызывает generate_schedule. Непустой результат
        заменяет сохранённый план; незапланированные остатки показываются отдельно.
        """
        # Получаем активные задачи из базы данных
        rows = self.db.get_tasks_for_scheduler()

        if not rows:
            QMessageBox.information(
                self,
                "Планировщик",
                "Нет активных задач для планирования."
            )
            return

        # Преобразуем записи БД в объекты Task
        tasks = []

        for task_id, title, priority, duration, deadline in rows:
            deadline_date = (
                date.fromisoformat(deadline)
                if deadline is not None
                else None
            )

            tasks.append(
                Task(
                    id=task_id,
                    title=title,
                    priority=priority,
                    duration=duration,
                    deadline=deadline_date
                )
            )

        # Получаем настройки из интерфейса
        start_date = self.plannerStartDateEdit.date().toPyDate()
        days = self.plannerDaysSpin.value()

        start_time = self.plannerStartTimeEdit.time().toPyTime()
        end_time = self.plannerEndTimeEdit.time().toPyTime()

        # Проверяем корректность времени
        if start_time >= end_time:
            QMessageBox.warning(
                self,
                "Ошибка",
                "Время окончания должно быть позже времени начала."
            )
            return

        # Формируем свободные интервалы
        free_slots = []
        now = datetime.now()

        for i in range(days):
            current_day = start_date + timedelta(days=i)

            slot_start = datetime.combine(
                current_day,
                start_time
            )

            slot_end = datetime.combine(
                current_day,
                end_time
            )

            # Полностью прошедшие интервалы пропускаем
            if slot_end <= now:
                continue

            # Если интервал уже начался, убираем прошедшее время
            if slot_start < now:
                slot_start = now.replace(
                    second=0,
                    microsecond=0
                )

                if slot_start < now:
                    # Сначала исключаем уже начавшуюся минуту, затем округляем до четверти часа.
                    slot_start += timedelta(minutes=1)

                # Округляем вверх до ближайших 15 минут
                extra = (-slot_start.minute) % 15
                slot_start += timedelta(minutes=extra)

            if slot_start < slot_end:
                free_slots.append(
                    FreeSlot(
                        start=slot_start,
                        end=slot_end
                    )
                )

        if not free_slots:
            QMessageBox.warning(
                self,
                "Планировщик",
                "Нет свободного времени в выбранном периоде."
            )
            return

        # Запускаем алгоритм из scheduler.py
        schedule, remaining = generate_schedule(
            tasks,
            free_slots
        )

        if not schedule:
            QMessageBox.warning(
                self,
                "Планировщик",
                "Не удалось распределить задачи по расписанию.\n"
                + self.describe_remaining(tasks, remaining, free_slots)
            )
            return

        # Сохраняем расписание в SQLite
        self.db.save_schedule(schedule)

        # Обновляем таблицу
        self.load_schedule()

        # Считаем незапланированное время
        unfinished = sum(
            minutes
            for minutes in remaining.values()
            if minutes > 0
        )

        if unfinished > 0:
            QMessageBox.warning(
                self,
                "Расписание составлено частично",
                f"Не удалось распределить {unfinished} минут работы.\n"
                + self.describe_remaining(tasks, remaining, free_slots)
            )
        else:
            QMessageBox.information(
                self,
                "Готово",
                "Все задачи успешно распределены!"
            )

    @staticmethod
    def describe_remaining(tasks, remaining, free_slots):
        """Возвращает текст со списком незапланированных минут и причинами.

        tasks — объекты Task, remaining — словарь {task_id: минуты},
        free_slots — непустой список доступных интервалов. Нулевые остатки пропускаются.
        """
        lines = []
        first_day = min(slot.start.date() for slot in free_slots)
        for task in tasks:
            minutes = remaining[task.id]
            if minutes <= 0:
                continue
            if task.deadline and task.deadline < date.today():
                reason = "срок уже истёк"
            elif task.deadline and task.deadline < first_day:
                reason = "срок раньше доступного периода"
            elif minutes < 15:
                reason = "остаток меньше 15 минут; проверьте длительность задачи"
            else:
                reason = "не хватило доступного времени до срока или конца периода"
            lines.append(f"• {task.title}: {minutes} мин — {reason}")
        return "\n".join(lines)

    def load_schedule(self):
        """Читает сохранённые блоки, форматирует даты и время, обновляет статистику."""
        # Загружаем запланированные занятия из SQLite
        rows = self.db.get_saved_schedule()

        # Очищаем таблицу перед обновлением
        self.scheduleTableWidget.setRowCount(0)

        for start_text, end_text, title, duration in rows:
            start = datetime.fromisoformat(start_text)
            end = datetime.fromisoformat(end_text)

            # Создаём строку таблицы
            row = self.scheduleTableWidget.rowCount()
            self.scheduleTableWidget.insertRow(row)

            values = [
                start.strftime("%d.%m.%Y"),
                start.strftime("%H:%M"),
                end.strftime("%H:%M"),
                title,
                f"{duration} мин"
            ]

            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                self.scheduleTableWidget.setItem(row, col, item)
        self.refresh_dashboard()

    def complete_task(self):
        """Отмечает выбранную активную задачу выполненной и обновляет интерфейс."""
        row = self.tasksTableWidget.currentRow()

        if row < 0:
            QMessageBox.warning(
                self,
                "Ошибка",
                "Сначала выберите задачу."
            )
            return

        item = self.tasksTableWidget.item(row, 0)
        task_id = item.data(Qt.ItemDataRole.UserRole)

        if self.db.complete_task(task_id):
            self.load_tasks()
            self.load_schedule()

if __name__ == "__main__":
    # Этот блок выполняется при запуске файла, но не при его импорте как модуля.
    app = QApplication(sys.argv)
    app.setApplicationName("StudyOS")

    try:
        window = MainWindow()
    except (OSError, sqlite3.Error) as error:
        QMessageBox.critical(None, "Не удалось открыть StudyOS", str(error))
        sys.exit(1)
    window.show()

    # Цикл событий Qt обрабатывает нажатия, перерисовку и таймеры до закрытия приложения.
    sys.exit(app.exec())
