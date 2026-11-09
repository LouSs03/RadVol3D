# Reconstrucción V2 experimental (LUNA16)

V2 corresponde a la corrida de entrenamiento `v3_fbp_residual_cbam_ssim`. No
reemplaza al modelo V1 ni al segmentador EN-2.

## Configuración

En el backend, conserva las variables de V1 y del segmentador. Con PyTorch
instalado, habilita V2 con estos valores en el entorno del servicio:

```dotenv
MODEL_BUCKET=radvol3d-models
EN1_V2_WEIGHTS_OBJECT=mejor_modelo_en1_v3.pth
```

El checkpoint se descarga por el mecanismo de caché existente. No se publica
en Git. Si V2 no está configurada o no carga, pedirla devuelve HTTP 503 y el
estudio sigue pendiente. No se ejecuta V1 en su lugar.

La interfaz elige el modelo al iniciar cada estudio:
`POST /studies/{code}/process?reconstruction=en1_luna16`. Para V1, el valor es
`en1`. Los clientes que no envían el parámetro mantienen el comportamiento
predeterminado del servidor. La etapa de reconstrucción guarda el modelo usado,
y `GET /studies/{code}/status` lo informa en `reconstruction_model`.

## Datos y alcance

- V2 recibe cuatro proyecciones LUNA16 de 128 x 128, en 0, 45, 90 y 135 grados.
  Son promedios normalizados en [0, 1], no las sumas de TA-2 que usa V1.
  El rango no certifica la geometría, así que usa proyecciones generadas para V2.
- La salida del modelo se reordena de índices ZYX a XYZ. Eso no recupera
  orientación física, lateralidad, espaciado ni el tamaño previo al recorte.
  La escala de las mallas y las medidas de las lesiones es nominal. El visor
  marca los resultados de V2 como experimentales y no muestra sus direcciones
  anatómicas en los cortes. No se valida la precisión de la segmentación con V2.
- Antes de habilitar en el servidor, comprueba RAM y tiempos con la tubería
  completa. Una inferencia local del checkpoint original usó un pico de
  aproximadamente 2.22 GiB en el proceso, sin ejecutar segmentación ni mallas.

Para una prueba web, usa los cuatro `.npy` individuales del mismo caso de
`05_Muestras_4_Angulos_Web_NPY_v3`. Cárgalos en su casilla o usa los sufijos
`000`, `045`, `090` y `135`. No cargues el arreglo combinado ni el volumen de
referencia como proyección.

## Entrega al responsable del despliegue

Fusionar esta rama mediante pull request después de que pasen las pruebas del
repositorio. El servicio que publique `radvol3d.main:app` debe instalar
`requirements.txt`, el paquete (`pip install -e .`) y PyTorch para CPU o la
plataforma de cómputo elegida. PyTorch es un extra opcional: instalar solo
`requirements.txt` deja ambos modelos neuronales no disponibles. Para CPU,
seguir [la instalación oficial de PyTorch](https://pytorch.org/get-started/locally/)
y seleccionar Linux, Pip y CPU. Ejecutar Uvicorn con **un trabajador**, sin
`--reload`; las tareas en segundo plano y su recuperación al reiniciar suponen
un único proceso.

Variables del backend (configurarlas en el proveedor, no en Git):

| Variable | Valor o acción |
| --- | --- |
| `SUPABASE_URL` | URL del proyecto de Supabase actual. |
| `SUPABASE_SERVICE_KEY` | Clave de servicio del mismo proyecto. |
| `DATABASE_URL` | URL PostgreSQL del mismo proyecto; es obligatoria para iniciar. |
| `STORAGE_BUCKET` | `radvol3d`. |
| `MODEL_BUCKET` | `radvol3d-models`. |
| `EN1_WEIGHTS_OBJECT` | Conservar la ruta de V1 ya configurada. |
| `EN2_WEIGHTS_OBJECT` | Conservar la ruta del segmentador ya configurada. |
| `EN1_V2_WEIGHTS_OBJECT` | `mejor_modelo_en1_v3.pth`. |
| `RECONSTRUCTION_STRATEGY` | `en1` (V1 sigue como predeterminada). |

Las consultas de solo lectura al proyecto configurado localmente devolvieron HTTP
200 para las tablas `study`, `organ`, `model`, ambos buckets y el objeto V2. Eso no
comprueba la contraseña PostgreSQL ni las variables del proveedor de despliegue.

**Memoria:** en la prueba local de las cuatro etapas, el proceso alcanzó
2 487 508 992 bytes de memoria residente máxima (aprox. 2,32 GiB). Se recomienda
una instancia con al menos 4 GiB para dejar margen al sistema y evitar ejecutar
varios estudios simultáneos hasta medir su consumo. Un plan de 512 MiB no alcanza.

Comprobación después de publicar:

1. Confirmar que `GET /health` responde y que el registro de arranque informa
   `reconstruction:en1_luna16` y `segmentation:lung` disponibles. `/health` por
   sí solo no confirma los modelos.
2. Crear un estudio pulmonar con código nuevo; cargar las cuatro proyecciones V2
   individuales y llamar `POST /studies/{code}/process?reconstruction=en1_luna16`.
   La respuesta inicial debe ser 202. No usar datos personales reales en la prueba.
3. Consultar `GET /studies/{code}/status` hasta `completed`: las cuatro etapas
   deben terminar y `reconstruction_model` debe ser
   `reconstruction_en1_luna16`.
4. Abrir `/static/#/viewer/{code}` y comprobar que se dibujan la malla y los tres
   cortes; descargar `volume.npy` y `organ.glb`. Comprobar en Supabase las filas
   del estudio y sus objetos almacenados. La prueba local completó las cuatro
   etapas, produjo un volumen 128³ y una malla de órgano no vacía, pero guardó
   sus resultados solo en memoria: todavía falta esta comprobación persistente.

La interfaz se sirve desde el mismo backend en `/static/` y usa rutas relativas
del mismo origen para la API. Si el equipo publica además un frontend separado,
debe coordinar su URL de API con el backend antes de probarlo.
