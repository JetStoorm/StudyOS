"""Создаёт презентацию и скриншоты на демонстрационной базе в памяти.

Запуск из корня проекта: python -B scripts/build_presentation.py.
Личные задачи и SQLite-файлы пользователя не используются.
"""

import os
import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path

if sys.platform != "win32":
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PyQt6.QtCore import QTime
from PyQt6.QtWidgets import QApplication
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.util import Inches, Pt

from main import MainWindow
from scheduler import Task, FreeSlot, generate_schedule


def capture_demo():
    """Сохраняет изображения главной страницы и расписания без личных данных."""
    images = ROOT / "docs" / "images"
    images.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    app.setStyle("Fusion")
    window = MainWindow(":memory:")
    try:
        tomorrow = date.today() + timedelta(days=1)
        window.db.add_subject("Математика")
        sid = window.db.get_subjects()[0][0]
        window.db.add_task("Подготовка к контрольной", sid, 1, 60, tomorrow.isoformat())
        window.db.add_task("Повторение формул", sid, 5, 60, (tomorrow + timedelta(days=1)).isoformat())
        window.db.add_task("Решение уравнений", sid, 3, 30, None)
        window.db.complete_task(window.db.get_tasks()[0][0])
        tasks = [Task(i, title, priority, duration, date.fromisoformat(deadline) if deadline else None)
                 for i, title, priority, duration, deadline in window.db.get_tasks_for_scheduler()]
        slots = [FreeSlot(datetime.combine(tomorrow + timedelta(days=i), time(17)),
                          datetime.combine(tomorrow + timedelta(days=i), time(18))) for i in range(2)]
        schedule, remaining = generate_schedule(tasks, slots)
        assert not any(remaining.values())
        assert schedule[0]["title"] == "Подготовка к контрольной"
        window.db.save_schedule(schedule)
        window.load_subjects()
        window.load_tasks()
        window.load_schedule()
        window.plannerStartDateEdit.setDate(tomorrow)
        window.plannerStartDateEdit.setDisplayFormat("dd.MM.yyyy")
        window.plannerDaysSpin.setValue(2)
        window.plannerStartTimeEdit.setTime(QTime(17, 0))
        window.plannerEndTimeEdit.setTime(QTime(18, 0))
        window.statusbar.showMessage("Демонстрационные данные · SQLite в памяти")
        window.show()
        for tab, name in ((window.dashboardTab, "dashboard.png"), (window.plannerTab, "schedule.png")):
            window.tabWidget.setCurrentWidget(tab)
            app.processEvents()
            assert window.grab().save(str(images / name))
    finally:
        window.close()


def add_text(slide, x, y, w, h, text, size=25, color="F4F7FA", bold=False):
    """Добавляет текстовый блок с переносами строк и единым оформлением."""
    box = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    frame = box.text_frame
    frame.word_wrap = True
    for index, line in enumerate(text.split("\n")):
        paragraph = frame.paragraphs[0] if index == 0 else frame.add_paragraph()
        paragraph.text = line
        paragraph.font.name = "Calibri"
        paragraph.font.size = Pt(size)
        paragraph.font.bold = bold
        paragraph.font.color.rgb = RGBColor.from_string(color)
        paragraph.space_after = Pt(16)


def build_slides():
    """Собирает десять слайдов с описанием фактических возможностей проекта."""
    deck = Presentation()
    deck.slide_width = Inches(13.333)
    deck.slide_height = Inches(7.5)
    deck.core_properties.title = "StudyOS — планирование самостоятельного обучения"
    deck.core_properties.author = "StudyOS"
    slides = [
        ("StudyOS", "От списка учебных задач\nк конкретному расписанию\n\nPython · PyQt6 · SQLite · EDF", None,
         "Представьтесь. StudyOS — локальное настольное приложение для самостоятельного обучения. Оно связывает задачи со свободными часами."),
        ("Проблема и цель", "Несколько предметов и разные сроки\nОграниченное свободное время\nНужен план: что и когда выполнять\nРезультат должен сохраняться после перезапуска", None,
         "Объясните отличие от простого списка дел: приложение распределяет работу по конкретным временным интервалам."),
        ("Основной сценарий", "01  Создать предмет и задачу\n02  Указать минуты, приоритет и срок\n03  Выбрать часы и составить план\n04  Отметить фактическое выполнение\n05  Посмотреть статистику и сохранить отчёт", None,
         "Покажите полный пользовательский цикл. Составление расписания не уменьшает фактически оставшуюся работу."),
        ("Архитектура", "main.py + ui/ → интерфейс и действия\ndatabase.py → SQL и транзакции\nscheduler.py → независимый алгоритм\nfile_exchange.py → CSV и TXT\napp_paths.py → постоянный каталог базы", None,
         "Планировщик не зависит от PyQt6 и SQLite. Интерфейс вызывает методы Database вместо собственных SQL-запросов. TaskDialog проверяет форму перед закрытием."),
        ("Модель данных SQLite", "subjects  1 → N  tasks  1 → N  planned_blocks\nЗадача: приоритет, длительность, остаток, срок\nСтатусы: active / completed / deleted\nВнешние ключи сохраняют связи\nТранзакция: все изменения или полный откат", None,
         "Одна задача может состоять из нескольких занятий. Новый план заменяет старый внутри одной транзакции. Удаление задачи логическое: запись остаётся для отчётности."),
        ("Алгоритм EDF: ближайший срок первым", "Ближайший срок → больший приоритет → ID\nЗадачи без срока рассматриваются последними\nСрочная задача с приоритетом 1 — сегодня\nНесрочная с приоритетом 5 — завтра\nЖадный алгоритм: глобальный оптимум не гарантирован", None,
         "Пример: свободно по часу сегодня и завтра. Обе задачи по 60 минут. Выбор только по приоритету мог вытеснить срочную задачу. EDF размещает её первой. Сложность O(S log S + (B + S) × N)."),
        ("Главная: состояние обучения", "Активные и завершённые\nПросроченные задачи\nПроцент выполнения\nНагрузка в минутах\nБлижайшие сроки", "dashboard.png",
         "Прогресс — завершённые делить на активные плюс завершённые. Удалённые не учитываются. Запланированное время — длительность незакончившихся блоков, а не фактические затраты."),
        ("Расписание занятий", "Период: 1–28 дней\nБлоки: 15–60 минут\nБез пересечений\nНе позже срока\nСохранение в SQLite", "schedule.png",
         "Покажите срочную задачу первой. Пересекающиеся входные интервалы объединяются. Конец блока не выходит за конец дня срока. При недостатке времени показывается остаток."),
        ("Обмен файлами и готовое приложение", "Импорт и экспорт задач CSV\nЭкспорт расписания CSV и отчёт TXT\nПроверка строк и пропуск точных дубликатов\nStudyOS.exe — без отдельной установки Python\nSQLite хранится отдельно в LocalAppData / StudyOS", None,
         "Меню Файл использует стандартные диалоги. CSV проверяется целиком до записи. Исходники размещаются в Git, а EXE можно прикрепить к GitHub Release."),
        ("Результат и дальнейшее развитие", "Реализован полный цикл планирования обучения\nИнтерфейс, данные и алгоритм разделены\nИсходный код содержит русские пояснения\nДальше: частичное выполнение и перерывы\nСпасибо! Вопросы?", None,
         "Продемонстрируйте сохранение после перезапуска и завершение задачи. Частичное выполнение, перерывы и разные часы по дням недели — идеи развития, а не текущие возможности."),
    ]
    for number, (title, body, image, notes) in enumerate(slides, 1):
        slide = deck.slides.add_slide(deck.slide_layouts[6])
        slide.background.fill.solid()
        slide.background.fill.fore_color.rgb = RGBColor.from_string("142334")
        add_text(slide, .6, .4, 12.1, .85, title, 34, bold=True)
        add_text(slide, .7, 1.65, 4.0 if image else 11.9, 4.9, body, 23 if image else 27)
        if image:
            slide.shapes.add_picture(str(ROOT / "docs/images" / image), Inches(5), Inches(1.45), width=Inches(7.4))
        add_text(slide, .6, 7.0, 11.8, .35, "STUDYOS  /  ПЛАНИРОВАНИЕ ОБУЧЕНИЯ", 11, "42D4BD")
        add_text(slide, 12.1, 7.0, .6, .35, f"{number:02}", 12, "42D4BD")
        slide.notes_slide.notes_text_frame.text = notes
    deck.save(ROOT / "docs/StudyOS_Presentation.pptx")


if __name__ == "__main__":
    capture_demo()
    build_slides()
    print("Created docs/StudyOS_Presentation.pptx and two demonstration screenshots.")
