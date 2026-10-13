# Mallas para el visor

`src/radvol3d/services/meshing/marching_cubes_strategy.py` genera los archivos `.glb` de cada
estudio con marching cubes (scikit-image) y los exporta con trimesh. Las dos bibliotecas
son gratuitas.

| Malla | Fuente | Umbral | Paso |
|---|---|---|---|
| `meshes/tumor.glb` | máscara de segmentación | 0,5 sobre la máscara binaria | 1 vóxel |
| `meshes/organ.glb` | una región del volumen reconstruido, según el órgano (ver abajo) | 0,5 sobre la región binaria | 2 vóxeles |
| `meshes/lesion_<NNN>.glb` | la región de una lesión dentro de la máscara | 0,5 sobre esa región | 1 vóxel |

El visor dibuja el órgano y una malla por lesión. `tumor.glb`, con todas las lesiones juntas,
se sigue generando y se ofrece para descargar.

## Malla de cada lesión (funcionalidad 004)

La segmentación entrega una sola máscara con todas las lesiones. Para separarlas,
`services/meshing/lesion_regions.py` (`split_lesion_masks`) empareja cada región del resumen
con una componente conexa de la máscara:

1. Etiqueta la máscara con `scipy.ndimage.label` y la conectividad por omisión, la misma que
   usa `summarize_regions`.
2. Cada región del resumen trae `voxels` y `centroid_voxel`. Se elige la componente con el
   mismo número de vóxeles y el mismo centroide redondeado.
3. Si una región no encuentra su componente, la etapa 4 falla: es un error de programa, y
   mezclar lesiones sería peor que fallar.

En EN-2 la correspondencia es exacta por construcción: la máscara ya viene limpia
(`clean_mask` con `min_voxeles`) y el resumen se calcula sobre esa misma máscara, así que cada
componente tiene exactamente una región.

El número `NNN` es la posición de la región en el resumen, desde `001`. No es `region_id`: el
enlace entre la fila de `lesion` y su malla es la columna `mesh_path`.

## Malla del órgano

La malla sale de una región binaria del volumen. Qué región es lo decide la
`OrganRegionStrategy` que la fábrica le da a cada órgano (`services/meshing/organ_region.py`):

| Órgano | Región | Suavizado (gauss / laplaciano) |
|---|---|---|
| pulmón | `LungAirRegion`: el aire que encierra el cuerpo | 1,5 / 5 |
| otros (por omisión) | `LargestComponentRegion`: el tejido más brillante | 2,5 / 10 |

### Por qué el pulmón necesita su propia región

En la ventana de -1000 a 1000 HU el pulmón es aire (~ -850 HU, 0,075) y lo brillante es el
cuerpo que lo rodea (tejido ~0,5). Otsu sobre el volumen se queda con el tejido: en un tórax,
la región "más brillante" es el cuerpo entero. Con los estudios `lung_001`, `lung_003` y
`lung_004` la malla del órgano medía de 7 a 14 L, un bloque con forma de caja, y la forma
del pulmón no se veía. El fantoma elipsoide de la referencia sí daba una forma perfecta,
porque es un objeto brillante sobre fondo negro.

### `LungAirRegion`

Todos los umbrales salen de cada volumen:

1. **Tejido**: Otsu del volumen. **Aire puro**: un segundo Otsu, solo sobre lo que no es
   tejido. En los seis volúmenes medidos dieron ≈ -490 HU y ≈ -890 HU.
2. **Cuerpo**: envolvente convexa del tejido, corte axial por corte axial (el eje axial es
   el eje de giro de TA-2). El pulmón cuenta como "dentro" aunque el campo de visión corte
   el cuerpo.
3. **Afuera**: el aire puro fuera del cuerpo, solo en los cortes con datos. Un estudio que
   termina en medio del pulmón deja cortes vacíos que no son "afuera".
4. **Candidatos**: lo que no es tejido dentro del cuerpo, con una apertura de radio 2. Incluye
   las zonas del pulmón que la reconstrucción deja casi en aire puro (~16 % del pulmón).
5. **Descarte**: componentes con mediana menor que 0,85 × el umbral de aire puro (gas,
   bolsas exteriores) o con más del 35 % de su superficie junto al aire puro de afuera
   (concavidades del cuerpo, mantas).
6. **Resultado**: hasta dos componentes (los dos pulmones), de al menos el 10 % de la mayor,
   con los vasos rellenos corte a corte.

Si no queda ninguna componente (un volumen sin aire encerrado, como el fantoma), se usa
`LargestComponentRegion`: mejor esa malla que ninguna.

### Cómo se midió

Con los volúmenes originales de los tres estudios se armaron variantes que simulan otros
pacientes y otras adquisiciones: más chico o más grande, rotado, desplazado, en espejo, con
menos cortes y con ruido en las proyecciones. Cada variante se proyectó con TA-2 y se
reconstruyó con EN-1. Los dos cortes del paso 5 se fijaron con **24 variantes de ajuste**
(en el medio del hueco medido entre pulmón y no pulmón) y el método se midió con **15
variantes de validación** distintas. La referencia es el pulmón del volumen original
suavizado.

| Validación (15 variantes) | Tejido (antes) | `LungAirRegion` |
|---|---|---|
| Dice medio contra el pulmón real | 0,02 | 0,84 |
| Distancia media entre superficies | 23,5 mm | 6,6 mm |
| Peor distancia | 31,7 mm | 11,9 mm |
| Variantes con Dice < 0,7 | 15 | 1 |

Comprobación independiente del método (`tests/ml/test_lung_organ_mesh.py`): la fracción de la
región que es aire o pulmón en la tomografía original fue de 0,89 a 0,95 con
`LungAirRegion` y de 0,03 a 0,11 con la región de tejido.

Lo que se probó y no se adoptó:

- **Solo geometría** (aire dentro de la envolvente, sin densidad): 8 de 24 variantes
  fallaron, varias con la región vacía.
- **Solo densidad** (entre aire puro y tejido, sin envolvente): 11 de 24; pierde el pulmón
  que la reconstrucción deja en aire puro.
- **Otsu de tres clases**: en los volúmenes originales corta en -500 y +100 HU (separa la
  grasa, no el pulmón).
- **Superficie desde la intensidad** en lugar de la región binaria: 6,40 mm frente a
  6,36 mm con la región binaria suavizada; no compensa la complejidad.
- **Quitar el gas pegado al pulmón** (apertura del aire puro dentro de la región): empeoró la
  validación (Dice 0,81, 7,1 mm).

### Limitaciones

- Son tres pacientes y variantes sintéticas, no un conjunto clínico. Hay que repetir la
  medición con más estudios reales.
- Una bolsa de gas pegada a la base del pulmón queda dentro de la malla (`lung_003`).
- Un paciente mucho más grande que el campo de visión (+40 %) baja el Dice a 0,63.
- Si el campo de visión trunca el cuerpo y la reconstrucción oscurece mucho ese borde (seis
  vóxeles o más), se puede perder un pulmón.
- La malla no puede ser mejor que la reconstrucción: con cuatro ángulos, EN-1 deja bandas y
  bordes blandos (FR-026a).

### Región por omisión: `LargestComponentRegion`

1. Umbral de Otsu sobre el volumen. No se fija ningún valor a mano.
2. Apertura con una esfera de radio 6, que recorta las puntas en estrella de la
   reconstrucción con cuatro ángulos.
3. Se conserva la región conexa más grande y se rellenan sus huecos, para descartar islas
   de ruido.

Lo que se midió con un volumen gaussiano con ruido de 128³ (research.md R19):

| Variante | GLB |
|---|---|
| Isosuperficie directa con Otsu | 21,2 MB |
| Componente más grande, paso 1 | 8,3 MB |
| Componente más grande, paso 2 (la elegida) | 1,2 MB |

**Limitación declarada (FR-026a).** La malla del órgano depende de la calidad de la
reconstrucción: si el volumen sale borroso, la superficie también.

### Estudios procesados antes de este cambio

Guardan la malla vieja. El volumen está guardado (`volume.npy`), así que se puede regenerar
solo la malla, sin volver a correr EN-1 ni EN-2. Todavía no hay un script para hacerlo.

## Coordenadas

- Milímetros, a 2,5 mm por vóxel.
- Ejes de numpy en el orden (0, 1, 2).
- Origen en el centro del volumen, es decir, en el centro del vóxel `(N - 1) / 2` de cada eje.

El órgano, el tumor y las lesiones comparten el sistema, así que el visor los superpone sin
transformar.

## Sin superficie

Hay tres casos sin superficie:

- máscara vacía, cuando no hay lesión (y entonces tampoco hay mallas de lesión);
- volumen constante;
- marching cubes sin superficie.

En los tres se exporta un `.glb` válido sin geometría, de 172 bytes con trimesh 5.1. El
estudio no falla, y el visor no tiene que distinguir esos casos.
