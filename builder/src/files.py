import os
import shutil
import logging

INCLUDE_ITEM = [".git", ".venv"]
EXCLUDE_ITEM = [".git", ".venv", "archives", "build", "build_scripts", "node_modules"]


def clear_directory_contents(directory_path):
    """Удаляет все содержимое указанной директории, кроме .git"""
    logging.info(f"\n--- Очищаю содержимое {directory_path} ---")

    if not os.path.exists(directory_path):
        logging.error(f"Директория не существует: {directory_path}")
        return False

    try:
        for item in os.listdir(directory_path):
            item_path = os.path.join(directory_path, item)

            if item in INCLUDE_ITEM:
                logging.warning(f"Пропускаю {item} директорию")
                continue

            try:
                if os.path.isfile(item_path) or os.path.islink(item_path):
                    os.remove(item_path)
                    logging.info(f"Удален файл: {item}")

                elif os.path.isdir(item_path):
                    shutil.rmtree(item_path)
                    logging.info(f"Удалена директория: {item}")

            except Exception as e:
                logging.error(f"Ошибка при удалении {item}: {e}")
                return False
        return True
    except Exception as e:
        logging.error(f"Ошибка при очистке директории: {e}")
        return False


def copy_directory_contents(src_path, dst_path):
    """Копирует содержимое из src_path в dst_path, исключая .git"""
    logging.info(f"\n--- Копирую содержимое из {src_path} в {dst_path} ---")

    if not os.path.exists(src_path):
        logging.error(f"Исходная директория не существует: {src_path}")
        return False

    if not os.path.exists(dst_path):
        logging.error(f"Целевая директория не существует: {dst_path}")
        return False

    try:
        for item in os.listdir(src_path):
            if item in EXCLUDE_ITEM:
                logging.warning(f"Пропускаю {item} директорию")
                continue

            src_item = os.path.join(src_path, item)
            dst_item = os.path.join(dst_path, item)

            try:
                if os.path.isfile(src_item):
                    shutil.copy2(src_item, dst_item)
                    logging.info(f"Скопирован файл: {item}")

                elif os.path.isdir(src_item):
                    shutil.copytree(src_item, dst_item, dirs_exist_ok=True)
                    logging.info(f"Скопирована директория: {item}")

            except Exception as e:
                logging.error(f"Ошибка при копировании {item}: {e}")
                return False
        return True
    except Exception as e:
        logging.error(f"Ошибка при копировании директории: {e}")
        return False


def _remove_path(path):
    """Удаляет файл, ссылку или директорию."""
    if os.path.isfile(path) or os.path.islink(path):
        os.remove(path)
        return
    if os.path.isdir(path):
        shutil.rmtree(path)


def sync_source_top_level_items(src_path, dst_path):
    """Синхронизирует target только по top-level элементам, которые есть в source."""
    logging.info(f"\n--- Синхронизирую top-level элементы из {src_path} в {dst_path} ---")

    if not os.path.exists(src_path):
        logging.error(f"Исходная директория не существует: {src_path}")
        return False

    if not os.path.exists(dst_path):
        logging.error(f"Целевая директория не существует: {dst_path}")
        return False

    try:
        for item in os.listdir(src_path):
            if item in EXCLUDE_ITEM:
                logging.warning(f"Пропускаю {item} директорию")
                continue

            src_item = os.path.join(src_path, item)
            dst_item = os.path.join(dst_path, item)

            try:
                if os.path.exists(dst_item) or os.path.islink(dst_item):
                    _remove_path(dst_item)
                    logging.info(f"Заменяю существующий target item: {item}")

                if os.path.isfile(src_item):
                    shutil.copy2(src_item, dst_item)
                    logging.info(f"Скопирован файл: {item}")
                elif os.path.isdir(src_item):
                    shutil.copytree(src_item, dst_item)
                    logging.info(f"Скопирована директория: {item}")
                else:
                    logging.warning(f"Пропускаю неподдерживаемый item: {item}")

            except Exception as e:
                logging.error(f"Ошибка при синхронизации {item}: {e}")
                return False
        return True
    except Exception as e:
        logging.error(f"Ошибка при синхронизации директорий: {e}")
        return False


def copy_file_to_repo2(repo2_path: str, file_relative_path: str):
    """Копирует файл из текущей директории в репозиторий №2"""
    logging.info(f"\n--- Копирую .env в {repo2_path} ---")

    current_dir = os.getcwd()
    env_source_path = os.path.join(current_dir, file_relative_path)
    logging.info(env_source_path)

    if not os.path.exists(env_source_path):
        logging.error(
            f"Файл {file_relative_path} не найден "
            f"в текущей директории: {current_dir}"
        )
        return False

    if not os.path.isfile(env_source_path):
        logging.error(
            f"{file_relative_path} в директории "
            f"не является файлом: {env_source_path}"
        )
        return False

    if not os.path.exists(repo2_path):
        logging.error(f"Целевая директория не существует: {repo2_path}")
        return False

    env_target_path = os.path.join(
        repo2_path,
        file_relative_path.split("\\")[-1]
    )

    try:
        logging.info(
            f"Попытка копирования файла {file_relative_path} "
            f"из {env_source_path} в {env_target_path}."
        )
        shutil.copy2(env_source_path, env_target_path)

        if os.path.exists(env_target_path):
            logging.info(
                f"Файл {file_relative_path} успешно скопирован и "
                "заменен (если существовал)."
            )
            return True
        else:
            logging.error(
                f"Ошибка: файл {file_relative_path} не был скопирован!"
            )
            return False

    except Exception as e:
        logging.error(f"Ошибка при копировании файла: {e}")
        return False


def check_repo(repo_path: str):
    """Проверяет существование репозитория."""
    if not os.path.exists(repo_path):
        logging.error(f"Ошибка: Репозиторий не найден по пути: {repo_path}")
        return False

    if not os.path.exists(os.path.join(repo_path, ".git")):
        logging.error(f"Ошибка: {repo_path} не является git репозиторием")
        return False
    return True
