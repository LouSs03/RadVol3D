"""Pruebas de la pizarra del trabajo externo (en cola, reconstruyendo)."""

import pytest

from radvol3d.domain.enums import RemoteJobState
from radvol3d.services.pipeline.remote_job_board import RemoteJobBoard


@pytest.mark.unit
def test_the_board_keeps_the_last_state_of_each_study_until_cleared() -> None:
    board = RemoteJobBoard()

    board.update("a", RemoteJobState.QUEUED)
    board.update("a", RemoteJobState.RUNNING)
    board.update("b", RemoteJobState.QUEUED)

    assert board.get("a") is RemoteJobState.RUNNING
    assert board.get("b") is RemoteJobState.QUEUED
    board.clear("a")
    board.clear("no_existe")
    assert board.get("a") is None
