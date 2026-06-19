"""
Пакет typed-конфигурации simple-deploy.

Здесь живут Pydantic-модели для двух разных, но связанных вещей.

``runtime.py`` описывает текущий контракт ``tools-ci/windows_pipeline.local.json``:
флаги включения maintenance/data SQL/healthcheck, таймауты, service steps,
management commands, email-настройки и другие параметры, которые отвечают на
вопрос "как именно выполнить текущий Windows runner".

``topology.py`` описывает целевую runtime topology: source origins, source
repositories, product components, virtual machines, deployment targets,
landscapes и execution environments. Это отвечает на вопрос "из каких частей
состоит система и куда они могут размещаться".

Пример различия:

* runtime config: ``data_sql_enabled=True`` и
  ``db_update_parallel_max_workers=4``;
* runtime topology: ``backend`` собирается из repo ``backend`` и размещается на
target-е роли ``backend`` в landscape ``dev``.

На текущем этапе ``RuntimeConfigModel`` является typed-оберткой над рабочим
JSON, а ``RuntimeTopologyConfigModel`` фиксирует целевую форму для следующих
срезов и пока не заменяет существующий loader.
"""

from simple_deploy.config.runtime import (
    runtime_config_model,
    RuntimeConfigModel,
    ServiceStepConfigModel,
    SqlScriptConfigModel,
)
from simple_deploy.config.topology import (
    ComponentConfigModel,
    DeploymentLandscapeConfigModel,
    DeploymentTargetConfigModel,
    ExecutionEnvironmentConfigModel,
    runtime_topology_config_model,
    runtime_topology_from_legacy_env,
    RuntimeTopologyConfigModel,
    SourceOriginConfigModel,
    SourceRepositoryConfigModel,
    VirtualMachineConfigModel,
)
from simple_deploy.config.validation import check_runtime_config

__all__ = [
    "ComponentConfigModel",
    "DeploymentLandscapeConfigModel",
    "DeploymentTargetConfigModel",
    "ExecutionEnvironmentConfigModel",
    "RuntimeConfigModel",
    "RuntimeTopologyConfigModel",
    "ServiceStepConfigModel",
    "SourceOriginConfigModel",
    "SourceRepositoryConfigModel",
    "SqlScriptConfigModel",
    "VirtualMachineConfigModel",
    "check_runtime_config",
    "runtime_config_model",
    "runtime_topology_config_model",
    "runtime_topology_from_legacy_env",
]
