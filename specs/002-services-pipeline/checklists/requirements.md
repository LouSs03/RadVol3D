# Specification Quality Checklist: Capa de servicios y tubería de procesamiento

**Purpose**: Validate specification completeness and quality before proceeding to planning
**Created**: 2026-10-09
**Feature**: [spec.md](../spec.md)

## Content Quality

- [x] No implementation details (languages, frameworks, APIs)
- [x] Focused on user value and business needs
- [x] Written for non-technical stakeholders
- [x] All mandatory sections completed

## Requirement Completeness

- [x] No [NEEDS CLARIFICATION] markers remain
- [x] Requirements are testable and unambiguous
- [x] Success criteria are measurable
- [x] Success criteria are technology-agnostic (no implementation details)
- [x] All acceptance scenarios are defined
- [x] Edge cases are identified
- [x] Scope is clearly bounded
- [x] Dependencies and assumptions identified

## Feature Readiness

- [x] All functional requirements have clear acceptance criteria
- [x] User scenarios cover primary flows
- [x] Feature meets measurable outcomes defined in Success Criteria
- [x] No implementation details leak into specification

## Notes

- **Excepción justificada en "Content Quality"** (la misma que en la funcionalidad 001). Esta
  funcionalidad es una capa interna, y quien la pidió fijó los nombres. Por eso la
  especificación nombra:
  - las interfaces, la fábrica, la tubería y `StudyService`;
  - los errores de `domain/exceptions.py`;
  - los archivos de `models/` y las bibliotecas de mallas.
  Todo eso lo dio el usuario o ya está en el repositorio y la constitución. La especificación
  no fija firmas, clases nuevas ni estructura interna. Los criterios de éxito se expresan en
  resultados observables (estados, archivos, tiempos, coincidencia numérica).
- **Iteración 1 (2026-10-09).** Quedan tres marcadores [NEEDS CLARIFICATION], todos
  descubiertos al leer `models/`:
  - FR-011: escala y formatos de entrada que espera EN-1.
  - FR-023: el archivo `en2_pulmon_mejor.pth` no tiene el formato que exige
    `en2_inferencia.py`.
  - FR-026: de qué superficie sale la malla del órgano.
- **Iteración 2 (2026-10-09).** Se resolvieron los tres marcadores (Q1: B, Q2: A, Q3: A) y se
  registraron en Clarifications:
  - FR-011: solo `.npy` en el convenio de TA-2, sin reescalar; PNG rechazado.
  - FR-023 y FR-023a: un script en `scripts/` genera el `.pth` de exportación de EN-2 y
    documenta el origen de cada valor. La estrategia envuelve `en2_inferencia.py` sin cambiar
    su lógica de carga.
  - FR-026 y FR-026a: la malla del órgano sale de la isosuperficie del volumen con umbral de
    Otsu. La dependencia de la calidad de la reconstrucción queda escrita, y el umbral fijo en
    HU, como mejora futura.
  Se agregaron tres casos borde: entrada en PNG, `.npy` con objetos y volumen constante. Se
  confirmaron FR-015 (borrado en la persistencia) y `trained_on` vacío. Todos los ítems pasan.
- Pendiente de datos reales (no son marcadores, son preguntas abiertas por el Principio V):
  `TODO(TRAINING_DATE_EN1)` y `TODO(TRAINING_DATE_EN2)`.
