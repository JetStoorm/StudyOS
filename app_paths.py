"""Постоянные пользовательские данные отдельно от ресурсов приложения."""

import os
import sqlite3
import sys
import tempfile
from pathlib import Path


def legacy_database_path():
    """Возвращает Path старой базы data/studyos.db рядом с исходниками или .exe."""
    # PyInstaller устанавливает sys.frozen; sys.executable тогда указывает на .exe,
    # а __file__ — на распакованные ресурсы, где постоянную базу искать не следует.
    root = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
    return root / "data" / "studyos.db"


def database_path():
    """Создаёт каталог данных и возвращает Path постоянной SQLite-базы.

    STUDYOS_DATA_DIR задаёт отдельный профиль без переноса старой базы.
    По умолчанию Windows использует LocalAppData/StudyOS, другие системы —
    XDG_DATA_HOME/StudyOS или ~/.local/share/StudyOS. При первом запуске
    в стандартном профиле копируется найденная старая база.
    """
    override = os.environ.get("STUDYOS_DATA_DIR")
    if override:
        directory = Path(override).expanduser().resolve()
    elif sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local"
        directory = Path(base) / "StudyOS"
    else:
        base = os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share"
        directory = Path(base) / "StudyOS"
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / "studyos.db"
    # При первом запуске переносим старые данные, не изменяя исходную базу.
    # Явно заданный каталог используется как независимый профиль (в т.ч. для тестов).
    source = legacy_database_path()
    if not override and not destination.exists() and source.is_file():
        migrate_database(source, destination)
    return destination


def migrate_database(source, destination):
    """Копирует SQLite-базу source в destination, сохраняя исходный файл.

    Пути принимаются как строки или Path. Возвращает True после переноса,
    False — если целевой файл уже существует. Ошибки файловой системы и SQLite
    передаются вызывающему коду. Backup учитывает журнал WAL (отдельный файл
    последних изменений); незавершённая временная копия удаляется при ошибке.
    """
    source, destination = Path(source), Path(destination)
    if destination.exists():
        return False
    destination.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(suffix=".db", dir=destination.parent)
    # Закрываем файловый дескриптор mkstemp перед открытием этого пути через SQLite.
    os.close(handle)
    try:
        # Режим ro не позволяет случайно изменить старую базу при копировании.
        original = sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True)
        copied = sqlite3.connect(temporary)
        try:
            original.backup(copied)
        finally:
            copied.close()
            original.close()
        # Windows rename не заменяет существующий файл при параллельном запуске.
        if destination.exists():
            return False
        Path(temporary).rename(destination)
        return True
    finally:
        # После успешного rename временного файла уже нет; missing_ok учитывает это.
        Path(temporary).unlink(missing_ok=True)
