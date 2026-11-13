"""CSV для обмена задачами и расписанием; человекочитаемый отчёт TXT."""

import csv
from datetime import date, datetime
from pathlib import Path

from database import Database


# Общий контракт импорта и экспорта: названия полей одинаковы в обе стороны.
TASK_COLUMNS = (
    "title", "subject", "priority", "duration_minutes",
    "remaining_minutes", "deadline", "status",
)


def read_tasks_csv(path):
    """Читает и проверяет CSV задач, возвращая список словарей для Database.import_tasks.

    path — путь к UTF-8 файлу с разделителем ';', BOM необязателен.
    Числовые поля преобразуются в int, пустой срок — в None.
    Ошибочные данные вызывают ValueError с номером строки, ошибки формата — csv.Error.
    Чтение файла не изменяет базу данных.
    """
    records = []
    # utf-8-sig принимает UTF-8 как с BOM, так и без него; newline='' нужен модулю csv.
    with open(path, encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream, delimiter=";", strict=True)
        if reader.fieldnames is None or len(reader.fieldnames) != len(TASK_COLUMNS) or set(reader.fieldnames) != set(TASK_COLUMNS):
            raise ValueError("Неверные столбцы CSV. Используйте файл, созданный экспортом задач.")
        for row in reader:
            try:
                # DictReader использует ключ None для лишних значений, а значение None — для недостающих.
                if None in row or any(value is None for value in row.values()):
                    raise ValueError("Количество значений не соответствует заголовку.")
                row = {key: value.strip() for key, value in row.items()}
                if not row["title"] or len(row["title"]) > 150 or not row["subject"]:
                    raise ValueError("Нужны название задачи (до 150 символов) и предмет.")
                for key in ("priority", "duration_minutes", "remaining_minutes"):
                    row[key] = int(row[key])
                if not 1 <= row["priority"] <= 5:
                    raise ValueError("Приоритет должен быть от 1 до 5.")
                Database.validate_duration(row["duration_minutes"])
                if not 0 <= row["remaining_minutes"] <= row["duration_minutes"]:
                    raise ValueError("Остаток должен быть от 0 до длительности задачи.")
                if row["remaining_minutes"] % 15:
                    raise ValueError("Остаток должен быть кратен 15 минутам.")
                if row["deadline"]:
                    parsed = date.fromisoformat(row["deadline"])
                    # Обратное форматирование требует именно ГГГГ-ММ-ДД, без сокращённых форм.
                    if parsed.isoformat() != row["deadline"]:
                        raise ValueError("Дата должна быть в формате ГГГГ-ММ-ДД.")
                else:
                    row["deadline"] = None
                if row["status"] not in ("active", "completed", "deleted"):
                    raise ValueError("Статус должен быть active, completed или deleted.")
                if row["status"] == "completed" and row["remaining_minutes"] != 0:
                    raise ValueError("У завершённой задачи остаток должен быть нулевым.")
                if row["status"] == "active" and row["remaining_minutes"] == 0:
                    raise ValueError("У активной задачи остаток должен быть больше нуля.")
            except ValueError as error:
                raise ValueError(f"Строка {reader.line_num}: {error}") from error
            records.append(row)
    return records


def import_tasks_csv(db, path):
    """Импортирует весь проверенный файл и возвращает (добавлено, пропущено).

    db — открытый Database. При неверной строке запись не начинается,
    а ошибка SQLite во время импорта откатывает всю транзакцию.
    """
    # Проверяем весь файл до первой записи в базу.
    return db.import_tasks(read_tasks_csv(path))


def export_tasks_csv(db, path):
    """Записывает задачи всех статусов в CSV и возвращает количество задач.

    Существующий файл path перезаписывается. UTF-8 с BOM помогает табличным
    редакторам распознать кириллицу; кавычки и переносы обрабатываются модулем csv.
    """
    records = db.get_export_tasks()
    with open(path, "w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=TASK_COLUMNS, delimiter=";")
        writer.writeheader()
        writer.writerows(records)
    return len(records)


def export_schedule_csv(db, path):
    """Записывает сохранённый план в CSV и возвращает число блоков.

    Столбцы: start_at, end_at, title, duration_minutes. Существующий файл
    перезаписывается; формат предназначен для экспорта, не для импорта задач.
    """
    rows = db.get_saved_schedule()
    with open(path, "w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream, delimiter=";")
        writer.writerow(("start_at", "end_at", "title", "duration_minutes"))
        writer.writerows(rows)
    return len(rows)


def export_report_txt(db, path):
    """Сохраняет читаемый UTF-8 отчёт: статистику, все задачи и расписание.

    db — открытый Database, path — путь назначения. Существующий файл
    перезаписывается; функция не возвращает результат и не изменяет данные в базе.
    """
    now = datetime.now()
    stats = db.get_statistics(now)
    lines = [
        "StudyOS — отчёт об обучении", f"Сформирован: {now:%d.%m.%Y %H:%M}", "",
        f"Активных задач: {stats['active']}", f"Завершённых задач: {stats['completed']}",
        f"Удалённых задач: {stats['deleted']}", f"Просроченных активных задач: {stats['overdue']}",
        f"Прогресс: {stats['completion_percent']}%",
        "Формула: завершённые / (активные + завершённые) × 100%; без задач — 0%.",
        f"Оставшаяся работа: {stats['remaining_minutes']} мин",
        f"Запланировано (незакончившиеся блоки целиком): {stats['planned_minutes']} мин",
        "Планирование не означает фактического выполнения.", "", "ЗАДАЧИ",
    ]
    records = db.get_export_tasks()
    for row in records:
        lines.append(
            f"{row['title']} | {row['subject']} | приоритет {row['priority']} | "
            f"{row['remaining_minutes']}/{row['duration_minutes']} мин | "
            f"срок: {row['deadline'] or 'без срока'} | {row['status']}"
        )
    if not records:
        lines.append("Задач нет.")
    lines.extend(("", "СОХРАНЁННОЕ РАСПИСАНИЕ"))
    schedule = db.get_saved_schedule()
    for start, end, title, minutes in schedule:
        lines.append(f"{start} — {end} | {title} | {minutes} мин")
    if not schedule:
        lines.append("Расписание пусто.")
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")
