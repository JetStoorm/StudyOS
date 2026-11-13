"""Независимый от интерфейса и SQLite алгоритм планирования учебных занятий.

Используется жадный выбор EDF (Earliest Deadline First): сначала ближайший срок.
План состоит из непересекающихся блоков длительностью 15, 30, 45 или 60 минут.
"""

from dataclasses import dataclass
from datetime import date, datetime, time
from datetime import timedelta


@dataclass
class Task:
    """Задача для планирования.

    id связывает результат с записью SQLite; title нужен для отображения.
    priority — приоритет (большее значение важнее), duration — оставшиеся минуты,
    deadline — последний допустимый день занятий или None, если срока нет.
    """

    id: int
    title: str
    priority: int
    duration: int
    deadline: date | None


@dataclass
class FreeSlot:
    """Свободный интервал [start, end): занятие может закончиться ровно в end.

    Границы задаются datetime в одном местном времени, end должен быть позже start.
    """

    start: datetime
    end: datetime

def generate_schedule(tasks, free_slots):
    """Распределяет задачи по свободным интервалам и возвращает (schedule, remaining).

    tasks — список Task с уникальными ID; free_slots — список FreeSlot.
    При равных сроках выбирается больший приоритет, затем меньший ID.
    Задачи без срока рассматриваются после задач со сроком.

    schedule — список словарей с task_id, title, start, end и duration.
    remaining — словарь {task_id: незапланированные минуты}. Исходные задачи
    и интервалы не изменяются. Неверный интервал вызывает ValueError.

    Сортировка S интервалов и выбор из N задач для B блоков требуют
    O(S log S + (B + S) * N) времени. Глобальная оптимальность не гарантируется.
    """
    schedule = []

    # Сколько минут работы осталось у каждой задачи.
    remaining = {
        task.id: task.duration
        for task in tasks
    }

    # Обрабатываем свободные интервалы по порядку.
    free_slots = sorted(
        free_slots,
        key=lambda slot: slot.start
    )

    # Объединяем пересекающиеся интервалы, чтобы не планировать время дважды.
    merged_slots = []
    for slot in free_slots:
        if slot.end <= slot.start:
            raise ValueError("Конец свободного интервала должен быть позже начала.")
        if merged_slots and slot.start < merged_slots[-1].end:
            merged_slots[-1].end = max(merged_slots[-1].end, slot.end)
        else:
            # Копируем интервал: объединение не должно менять переданные объекты FreeSlot.
            merged_slots.append(FreeSlot(slot.start, slot.end))

    for slot in merged_slots:
        current_time = slot.start

        while current_time < slot.end:

            # Остатки меньше 15 минут пропускаются, чтобы не блокировать остальные задачи.
            # До конца дня срока должно помещаться хотя бы 15 минут.
            # Для date.max не прибавляем день: это вышло бы за диапазон datetime.
            available_tasks = [
                task
                for task in tasks
                if remaining[task.id] >= 15
                   and (
                           task.deadline is None
                            or current_time.date() <= task.deadline
                    )
                   and (task.deadline is None or task.deadline == date.max
                        or current_time + timedelta(minutes=15) <= datetime.combine(
                            task.deadline + timedelta(days=1), time.min))
            ]

            if not available_tasks:
                break

            # Срочность важнее приоритета: несрочная задача не вытесняет срочную.
            selected_task = min(
                available_tasks,
                key=lambda task: (
                    # False меньше True: задачи со сроком получают преимущество.
                    task.deadline is None,
                    task.deadline or date.max,
                    # min выбирает меньшее число, поэтому знак приоритета инвертирован.
                    -task.priority,
                    task.id,
                )
            )

            # Ограничиваем блок свободным временем и концом дня срока.
            free_minutes = int(
                (slot.end - current_time).total_seconds() // 60
            )
            if selected_task.deadline is not None and selected_task.deadline != date.max:
                # Срок включает весь день; его верхняя граница — полночь следующего дня.
                deadline_end = datetime.combine(
                    selected_task.deadline + timedelta(days=1), time.min
                )
                free_minutes = min(free_minutes, int(
                    (deadline_end - current_time).total_seconds() // 60
                ))

            block_minutes = min(
                60,
                remaining[selected_task.id],
                free_minutes
            )
            # Округление вниз не даёт блоку выйти за свободное время или срок.
            block_minutes = (block_minutes // 15) * 15

            if block_minutes < 15:
                break

            end_time = current_time + timedelta(
                minutes=block_minutes
            )

            # Добавляем блок.
            schedule.append({
                "task_id": selected_task.id,
                "title": selected_task.title,
                "start": current_time,
                "end": end_time,
                "duration": block_minutes
            })

            # Уменьшается только локальный остаток, а не прогресс в базе.
            remaining[selected_task.id] -= block_minutes
            current_time = end_time


    return schedule, remaining
