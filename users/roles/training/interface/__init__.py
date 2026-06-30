"""Superfície pública in-process do `training` (CONVENTION §3): o que `candidate`, o grupo
`collaborators` e os grupos `staff`/`leadership` chamam. Fina — reexporta a lógica do `service`.

Modelo novo (Victor 2026-06-16): treino = trava pós-promotor por matérias (não há mais entrevista).
"""

from users.roles.training.service import (
    TrainingError,
    assign_material,
    assigned_materials,
    coordinator_approve_material,
    create_material,
    delete_material,
    is_locked,
    list_locked_promoters_for_hub,
    list_materials,
    material_to_dict,
    on_became_promoter,
    pending_materials,
    progress,
    publish_transitory,
    set_material_video,
    submission_to_dict,
    submit,
    update_material,
)

__all__ = [
    "TrainingError",
    # autoria de matéria (staff + coordenador)
    "create_material",
    "update_material",
    "delete_material",
    "set_material_video",
    "list_materials",
    "material_to_dict",
    "publish_transitory",
    # atribuição + trava
    "assign_material",
    "on_became_promoter",
    "is_locked",
    "pending_materials",
    "assigned_materials",
    "coordinator_approve_material",
    "list_locked_promoters_for_hub",
    # submissão
    "submit",
    "submission_to_dict",
    "progress",
]
