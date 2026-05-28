from src.infra import (
    get_new_branch_name,
    get_new_build_version,
)

from src.build_backend import build_backend
from src.build_frontend import build_frontend

if __name__ == "__main__":
    # TODO добавить параметризацию веток репозиториев, на основе которых происходит сборка.
    # TODO добавить last commits для репозиториев, на основе которых была проведена сборка.
    # TODO добавить сохранение логов сборщика в файл.
    # TODO добавить возможность ручного ввода версии релиза, помимо автоматической,
    # через .env файл.
    build_version = get_new_build_version()
    branch_name = get_new_branch_name(build_version=build_version)

    build_backend(
        build_version=build_version,
        branch_name=branch_name,
    )

    build_frontend(
        build_version=build_version,
        branch_name=branch_name,
    )

    # TODO собирать summary и roles нужно на этапе пре-пушей.


    # ERROR удаляется архивес из финального пуша, что логично.