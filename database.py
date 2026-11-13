"""Доступ к SQLite: предметы, задачи, расписание, статистика и пакетный импорт.

Пользовательские значения передаются через параметры SQL (знаки ?).
Блок with self.connection фиксирует изменения при успехе и откатывает при исключении.
"""

import sqlite3
from datetime import date, datetime
from pathlib import Path

from app_paths import database_path


class Database:
    """Хранит соединение SQLite и предоставляет операции над данными приложения."""

    def __init__(self, db_path=None):
        """Открывает базу и создаёт недостающие таблицы, сохраняя существующие записи.

        db_path: путь к файлу, None для стандартного пользовательского каталога
        или ':memory:' для базы, существующей только до закрытия соединения.
        """
        if db_path is None:
            db_path = database_path()
        if str(db_path) != ":memory:":
            db_path = Path(db_path)
            db_path.parent.mkdir(parents=True, exist_ok=True)

        self.path = str(db_path)
        self.connection = sqlite3.connect(db_path)
        # SQLite требует явно включить проверку внешних ключей для каждого соединения.
        self.connection.execute("PRAGMA foreign_keys = ON")

        with self.connection:
            self.connection.execute("""
                CREATE TABLE IF NOT EXISTS subjects (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE
                )
            """)

        self.connection.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                subject_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                priority INTEGER NOT NULL CHECK(priority BETWEEN 1 AND 5),
                duration_minutes INTEGER NOT NULL CHECK(duration_minutes > 0),
                remaining_minutes INTEGER NOT NULL,
                deadline TEXT,
                status TEXT NOT NULL DEFAULT 'active',

                FOREIGN KEY (subject_id)
                    REFERENCES subjects(id)
            )
        """)

        with self.connection:
            self.connection.execute("""
                CREATE TABLE IF NOT EXISTS planned_blocks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id INTEGER NOT NULL REFERENCES tasks(id),
                    start_at TEXT NOT NULL,
                    end_at TEXT NOT NULL,
                    duration_minutes INTEGER NOT NULL CHECK(duration_minutes > 0),
                    CHECK(end_at > start_at)
                )
            """)

    def get_subjects(self):
        """Возвращает список кортежей (id, name), отсортированный по названию."""
        cursor = self.connection.execute(
            "SELECT id, name FROM subjects ORDER BY name"
        )
        return cursor.fetchall()

    def add_subject(self, name):
        """Добавляет предмет; повторное название вызывает sqlite3.IntegrityError."""
        with self.connection:
            self.connection.execute(
                "INSERT INTO subjects (name) VALUES (?)",
                (name,)
            )

    def update_subject(self, subject_id, name):
        """Изменяет название предмета по ID, сохраняя его связи с задачами."""
        with self.connection:
            self.connection.execute(
                "UPDATE subjects SET name = ? WHERE id = ?",
                (name, subject_id)
            )

    def delete_subject(self, subject_id):
        """Удаляет предмет по ID.

        Если на него ссылается хотя бы одна задача любого статуса,
        внешний ключ запрещает удаление и SQLite вызывает IntegrityError.
        """
        with self.connection:
            self.connection.execute(
                "DELETE FROM subjects WHERE id = ?",
                (subject_id,)
            )

    def close(self):
        """Закрывает соединение; дальнейшие запросы через этот объект недопустимы."""
        self.connection.close()

    def add_task(self, title, subject_id, priority, duration, deadline):
        """Добавляет активную задачу с оставшимся временем, равным её длительности.

        duration задаётся в минутах, priority — от 1 до 5,
        deadline — строка ГГГГ-ММ-ДД или None для задачи без срока.
        """
        self.validate_duration(duration)
        with self.connection:
            self.connection.execute("""
                INSERT INTO tasks (
                    title,
                    subject_id,
                    priority,
                    duration_minutes,
                    remaining_minutes,
                    deadline
                )
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                title,
                subject_id,
                priority,
                duration,
                duration,
                deadline
            ))

    def get_tasks(self):
        """Возвращает активные задачи от новых к старым для таблицы интерфейса.

        Строка: (id, title, название предмета, priority, duration_minutes, deadline).
        """
        cursor = self.connection.execute("""
            SELECT
                tasks.id,
                tasks.title,
                subjects.name,
                tasks.priority,
                tasks.duration_minutes,
                tasks.deadline
            FROM tasks
            JOIN subjects
                ON tasks.subject_id = subjects.id
            WHERE tasks.status = 'active'
            ORDER BY tasks.id DESC
        """)

        return cursor.fetchall()

    def get_task(self, task_id):
        """Возвращает активную задачу по ID или None, если она не найдена.

        Строка: (id, title, subject_id, priority, duration_minutes, deadline).
        """
        cursor = self.connection.execute("""
            SELECT id, title, subject_id, priority,
                   duration_minutes, deadline
            FROM tasks
            WHERE id = ? AND status = 'active'
        """, (task_id,))

        return cursor.fetchone()

    def update_task(self, task_id, title, subject_id,
                    priority, duration, deadline):
        """Обновляет активную задачу, сохраняя уже выполненный объём работы.

        Новый остаток = новая длительность минус выполненные минуты, но не меньше 0.
        Изменение приоритета, длительности или срока удаляет незакончившиеся блоки
        этой задачи в той же транзакции.
        """
        self.validate_duration(duration)
        with self.connection:
            old_task = self.get_task(task_id)
            # Разность старой длительности и остатка показывает уже выполненную работу.
            self.connection.execute("""
                UPDATE tasks
                SET title = ?,
                    subject_id = ?,
                    priority = ?,
                    remaining_minutes = MAX(
                        0,
                        ? - (duration_minutes - remaining_minutes)
                    ),
                    duration_minutes = ?,
                    deadline = ?
                WHERE id = ? AND status = 'active'
            """, (
                title,
                subject_id,
                priority,
                duration,
                duration,
                deadline,
                task_id
            ))
            if old_task and (old_task[3], old_task[4], old_task[5]) != (priority, duration, deadline):
                self.connection.execute("""
                    DELETE FROM planned_blocks
                    WHERE task_id = ? AND end_at > ?
                """, (task_id, datetime.now().isoformat(timespec="minutes")))

    @staticmethod
    def validate_duration(duration):
        """Проверяет диапазон 15–1440 минут и кратность 15; иначе вызывает ValueError."""
        if duration < 15 or duration > 1440 or duration % 15:
            raise ValueError("Продолжительность должна быть от 15 до 1440 минут и кратна 15.")

    def delete_task(self, task_id):
        """Ставит статус deleted и удаляет блоки задачи; сама запись остаётся в базе."""
        with self.connection:
            self.connection.execute("""
                UPDATE tasks
                SET status = 'deleted'
                WHERE id = ?
            """, (task_id,))

            self.connection.execute(
                "DELETE FROM planned_blocks WHERE task_id = ?", (task_id,)
            )

    def complete_task(self, task_id):
        """Завершает активную задачу, обнуляет остаток и удаляет её блоки.

        Возвращает True при изменении записи и False, если активная задача не найдена.
        """
        with self.connection:
            cursor = self.connection.execute("""
                UPDATE tasks
                SET status = 'completed',
                    remaining_minutes = 0
                WHERE id = ? AND status = 'active'
            """, (task_id,))

            if cursor.rowcount == 0:
                return False

            # Убираем запланированные занятия завершённой задачи.
            self.connection.execute("""
                DELETE FROM planned_blocks
                WHERE task_id = ?
            """, (task_id,))

        return True

    def get_tasks_for_scheduler(self):
        """Возвращает (id, title, priority, remaining_minutes, deadline) для планирования.

        Выбираются только активные задачи с положительным остатком работы.
        """
        cursor = self.connection.execute("""
            SELECT id, title, priority, remaining_minutes, deadline
            FROM tasks
            WHERE status = 'active'
              AND remaining_minutes > 0
        """)
        return cursor.fetchall()

    def save_schedule(self, schedule):
        """Заменяет весь план списком блоков generate_schedule в одной транзакции.

        Блок содержит task_id, start/end как datetime и duration в минутах.
        Даты сохраняются в ISO-формате. При ошибке старое расписание восстанавливается
        откатом транзакции; фактический остаток задач не изменяется.
        """
        with self.connection:
            self.connection.execute(
                "DELETE FROM planned_blocks"
            )

            self.connection.executemany("""
                INSERT INTO planned_blocks (
                    task_id,
                    start_at,
                    end_at,
                    duration_minutes
                )
                VALUES (?, ?, ?, ?)
            """, [
                (
                    block["task_id"],
                    block["start"].isoformat(timespec="minutes"),
                    block["end"].isoformat(timespec="minutes"),
                    block["duration"]
                )
                for block in schedule
            ])

    def get_saved_schedule(self):
        """Возвращает блоки активных задач по времени начала.

        Строка: (start_at, end_at, title, duration_minutes); даты представлены строками.
        """
        cursor = self.connection.execute("""
            SELECT
                p.start_at,
                p.end_at,
                t.title,
                p.duration_minutes
            FROM planned_blocks AS p
            JOIN tasks AS t ON t.id = p.task_id
            WHERE t.status = 'active'
            ORDER BY p.start_at
        """)
        return cursor.fetchall()

    def get_statistics(self, now=None):
        """Возвращает словарь счётчиков, минут и процента завершения на момент now.

        По умолчанию используется текущее местное время. Удалённые задачи исключены
        из процента выполнения. Запланированные минуты включают полную длительность
        незакончившихся блоков, а не фактически затраченное время.
        """
        now = now or datetime.now()
        counts = dict(self.connection.execute(
            "SELECT status, COUNT(*) FROM tasks GROUP BY status"
        ).fetchall())
        active = counts.get("active", 0)
        completed = counts.get("completed", 0)
        # COALESCE заменяет NULL от суммы по пустой таблице на привычный ноль.
        overdue, remaining = self.connection.execute("""
            SELECT COALESCE(SUM(deadline < ?), 0), COALESCE(SUM(remaining_minutes), 0)
            FROM tasks WHERE status = 'active'
        """, (now.date().isoformat(),)).fetchone()
        planned = self.connection.execute("""
            SELECT COALESCE(SUM(p.duration_minutes), 0)
            FROM planned_blocks p JOIN tasks t ON t.id = p.task_id
            WHERE t.status = 'active' AND p.end_at > ?
        """, (now.isoformat(timespec="minutes"),)).fetchone()[0]
        return {
            "active": active, "completed": completed,
            "deleted": counts.get("deleted", 0), "overdue": overdue,
            "remaining_minutes": remaining, "planned_minutes": planned,
            "completion_percent": round(100 * completed / (active + completed)) if active + completed else 0,
        }

    def get_upcoming_deadlines(self, today=None, limit=5):
        """Возвращает до limit активных задач со сроком не раньше today (по умолчанию сегодня).

        Строка: (title, название предмета, deadline, remaining_minutes).
        Просроченные задачи и задачи без срока в этот список не входят.
        """
        today = today or date.today()
        return self.connection.execute("""
            SELECT t.title, s.name, t.deadline, t.remaining_minutes
            FROM tasks t JOIN subjects s ON s.id = t.subject_id
            WHERE t.status = 'active' AND t.deadline >= ?
            ORDER BY t.deadline, t.priority DESC, t.id LIMIT ?
        """, (today.isoformat(), limit)).fetchall()

    def get_export_tasks(self):
        """Возвращает задачи всех статусов как словари с именами столбцов CSV."""
        cursor = self.connection.execute("""
            SELECT t.title, s.name AS subject, t.priority, t.duration_minutes,
                   t.remaining_minutes, t.deadline, t.status
            FROM tasks t JOIN subjects s ON s.id = t.subject_id ORDER BY t.id
        """)
        columns = [column[0] for column in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def import_tasks(self, records):
        """Добавляет проверенные записи CSV одной транзакцией и создаёт новые предметы.

        records — список словарей, подготовленный read_tasks_csv.
        Точные дубликаты пропускаются; существующие задачи не обновляются.
        Возвращает пару (число добавленных задач, число пропущенных дубликатов).
        """
        added = skipped = 0
        with self.connection:
            for record in records:
                self.validate_duration(record["duration_minutes"])
                self.connection.execute(
                    "INSERT OR IGNORE INTO subjects (name) VALUES (?)", (record["subject"],)
                )
                subject_id = self.connection.execute(
                    "SELECT id FROM subjects WHERE name = ?", (record["subject"],)
                ).fetchone()[0]
                values = (record["title"], subject_id, record["priority"],
                          record["duration_minutes"], record["remaining_minutes"],
                          record["deadline"], record["status"])
                # IS, в отличие от =, позволяет сопоставить два отсутствующих срока (NULL).
                exists = self.connection.execute("""
                    SELECT 1 FROM tasks WHERE title = ? AND subject_id = ? AND priority = ?
                    AND duration_minutes = ? AND remaining_minutes = ?
                    AND deadline IS ? AND status = ?
                """, values).fetchone()
                if exists:
                    skipped += 1
                    continue
                self.connection.execute("""
                    INSERT INTO tasks (title, subject_id, priority, duration_minutes,
                                       remaining_minutes, deadline, status)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, values)
                added += 1
        return added, skipped
