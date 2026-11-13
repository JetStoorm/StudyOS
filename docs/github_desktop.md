# Публикация StudyOS через GitHub Desktop

## Репозиторий

1. Откройте GitHub Desktop и войдите в свой GitHub-аккаунт.
2. Выберите **File → Add local repository** и папку этого проекта.
3. Если локальный репозиторий ещё не создан, используйте **create a repository here**.
   Убедитесь, что выбран существующий StudyOS, а не вложенная папка StudyOS/StudyOS.
4. Если есть неподтверждённые изменения, просмотрите их и сделайте **Commit to main**.
5. Нажмите **Publish repository**.
6. Name: **StudyOS**.
7. Description: **Локальный планировщик самостоятельного обучения на Python, PyQt6 и SQLite.**
8. Снимите **Keep this code private** для публичного репозитория.
9. Нажмите **Publish repository**, затем **Repository → View on GitHub**.

В список публикации не должны входить `.venv`, `.idea`, `data`, `dist`, `build`,
базы SQLite и `studyos_report.txt`. Эти пути уже исключены через `.gitignore`.
README и презентация должны присутствовать.

## Готовое приложение в Releases

1. На странице репозитория откройте **Releases → Create a new release**.
2. Создайте тег `v1.0.0`, заголовок `StudyOS 1.0.0`.
3. Прикрепите локальный файл `dist/StudyOS.exe`.
4. В описании укажите: Windows x64; отдельная установка Python не нужна;
   данные хранятся в `%LOCALAPPDATA%\StudyOS`.
5. Нажмите **Publish release**.

Не прикрепляйте личную базу данных. При изменении кода сначала пересоберите `.exe`.

## Последующие изменения

Измените файлы → просмотрите **Changes** в Desktop → напишите краткое описание →
**Commit to main → Push origin**. Изменения README автоматически появятся
на главной странице репозитория после Push.
