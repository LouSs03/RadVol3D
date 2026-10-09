"""Caso de uso: crear, consultar y borrar estudios."""

from radvol3d.domain.entities import Study


class StudyService:
    """Coordina la tuberia con la persistencia."""

    def get_study(self, study_code: str) -> Study:
        raise NotImplementedError("TODO")

    def delete_study(self, study_code: str) -> None:
        raise NotImplementedError("TODO")
