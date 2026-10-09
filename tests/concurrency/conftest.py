"""Las pruebas de concurrencia usan la misma base y bucket de prueba que las de integracion.

Se reutilizan las fixtures de tests/integration/conftest.py, incluida la limpieza de
los estudios "it_". Sin .env.test, se omiten.
"""

from tests.integration.conftest import (  # noqa: F401 - fixtures que pytest descubre aqui
    cleanup_after_test,
    created_patient_codes,
    database,
    make_study_code,
    object_storage,
    test_settings,
)
