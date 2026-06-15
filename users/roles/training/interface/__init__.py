"""Superfície pública in-process do `training` (CONVENTION §3): o que `candidate`, o grupo
`collaborators` e os grupos `staff`/`leadership` chamam. Fina — reexporta a lógica do `service`.
"""

from users.roles.training.service import (
    TrainingError,
    approve_interview,
    create_material,
    create_trainee,
    get_trainee_for_user_external_id,
    list_awaiting_interview_for_hub,
    list_materials,
    material_to_dict,
    progress,
    reject_interview,
    submission_to_dict,
    submit,
    trainee_detail_for_coordinator,
    trainee_to_dict,
    update_material,
)

__all__ = [
    "TrainingError",
    "create_trainee",
    "get_trainee_for_user_external_id",
    "trainee_to_dict",
    "trainee_detail_for_coordinator",
    "create_material",
    "update_material",
    "list_awaiting_interview_for_hub",
    "list_materials",
    "material_to_dict",
    "submit",
    "submission_to_dict",
    "progress",
    "approve_interview",
    "reject_interview",
]
