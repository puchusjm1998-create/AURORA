# Decisiones técnicas

Registro de las decisiones que condicionan el diseño, con la alternativa descartada y el motivo.
Cuando una decisión cambie, se añadirá una nueva entrada en lugar de reescribir la historia.

## D-01. SQLite en desarrollo, PostgreSQL en producción

**Decisión.** SQLAlchemy 2 con `DATABASE_URL`; SQLite para desarrollo y pruebas; PostgreSQL con
psycopg para entornos reales. `Settings.assert_safe()` impide arrancar en producción con SQLite.

**Motivo.** El entorno de desarrollo no dispone de PostgreSQL, pero el modelo debe ser portable.
Se evitan características exclusivas de SQLite; los enums se guardan como texto validado por
Pydantic y la lógica transaccional es la misma.

**Descartado.** Un ORM distinto por entorno o mocks de base de datos en pruebas: habrían ocultado
errores reales de SQL y de integridad.

## D-02. Enums como texto con validación, no enums nativos

**Decisión.** `SQLEnum(..., native_enum=False)` con `String` y validación en Python.

**Motivo.** PostgreSQL obliga a migraciones delicadas para añadir valores a un tipo nativo; SQLite
no los soporta. El texto es portable y las migraciones son aditivas.

## D-03. Identidad: UUID internos y códigos legibles

**Decisión.** Claves primarias UUIDv4 y, además, códigos legibles (`AUR-PAL-000001`) generados por
la tabla `code_sequences` con bloqueo transaccional. Los códigos no se reutilizan nunca.

**Motivo.** Los UUID no filtran volumen de negocio ni permiten enumeración; los códigos legibles son
imprescindibles en etiquetas, partes de trabajo y soporte telefónico. Guardar ambos evita tener que
elegir entre seguridad y usabilidad.

## D-04. `stock_levels` es la única fuente de verdad

**Decisión.** El stock se modifica únicamente dentro de `StockEngine` al confirmar un movimiento, en
la misma transacción, con `SELECT ... FOR UPDATE` cuando el motor lo permite.

**Motivo.** Evita dobles conteos y carreras entre recepción, expedición y reservas. `movement_allocations`
registra qué fila de stock se tocó para poder auditar y compensar con precisión.

**Descartado.** Recalcular el stock sumando movimientos en cada consulta: correcto en teoría, pero
costoso con decenas de miles de movimientos y propenso a inconsistencias por movimientos cancelados.

## D-05. Movimientos con estados, idempotencia y sin borrado

**Decisión.** `draft → confirmed | cancelled`. Cada alta acepta `idempotency_key` única; el
movimiento cancelado permanece y genera una compensación.

**Motivo.** La regla del cliente es no borrar histórico ni duplicar movimientos. Reintentos de red
o dobles clics no pueden alterar el stock dos veces. La cancelación es un hecho auditables, no un
borrado.

## D-06. RBAC en base de datos y verificación en servidor

**Decisión.** Tablas `roles` (nivel 1–5), `permissions` y `role_permissions`; dependencia
`require_permission` en cada ruta. Reglas adicionales: no elevar el propio nivel, no modificarse a
sí mismo, no crear roles superiores.

**Motivo.** El frontend puede ocultar botones, pero nunca debe ser la autoridad. El nivel 5 (auditor)
solo lee; los ajustes y regularizaciones exigen nivel ≤ 2 porque alteran valor contable.

**Descartado.** Listas de permisos en el token sin consulta a base de datos: un cambio de rol no
tendría efecto hasta caducar el token.

## D-07. Sesiones JWT revocables

**Decisión.** JWT firmado con `jti` que debe existir en `user_sessions`; `token_version` en el
usuario invalida tokens antiguos al cambiar la contraseña o cerrar todas las sesiones.

**Motivo.** Un JWT puro no se puede revocar. La comprobación en cada petición permite expulsar a un
trabajador de inmediato sin renunciar a la simplicidad del token.

## D-08. Auditoría append-only con triggers

**Decisión.** `audit_logs` se escribe en la misma transacción que la operación y triggers de base de
datos rechazan `UPDATE`/`DELETE`; también se protege el borrado de movimientos.

**Motivo.** La aplicación no debe ser la única barrera. Un acceso directo a la base de datos tampoco
puede reescribir la historia.

## D-09. Trazabilidad por producto (`tracking_mode`)

**Decisión.** Cada producto declara `quantity` (cantidad), `batch` (lote obligatorio) o `unit`
(números de serie y objetos `AUR-OBJ-*`).

**Motivo.** No todos los almacenes necesitan serialización. Forzar series a tornillería penaliza la
operación; permitir cantidades en equipos médicos rompe la trazabilidad. El modo se decide por
producto y se valida en el servidor.

## D-10. QR con esquema propio y código legible

**Decisión.** El QR codifica `aurora://tipo/código`; la etiqueta imprime además el código en texto.
El escaneo se resuelve contra `/scan/resolve` y nunca contiene datos personales.

**Motivo.** Un QR con URL absoluta queda atado al dominio de despliegue y expira si cambia. El
esquema propio es estable, y el código legible permite operar si la cámara falla.

## D-11. Frontend estático servido por FastAPI

**Decisión.** Next.js con `output: "export"` y `trailingSlash`; FastAPI sirve `frontend/out`
resolviendo rutas de directorio (`/pale/` → `pale/index.html`) y devuelve la página 404 de Next
para rutas inexistentes.

**Motivo.** Mismo origen ⇒ cookie first-party sin CORS ni proxy adicional, menos superficie de
despliegue y PWA sencilla. El coste es renunciar a SSR dinámico, aceptable porque la aplicación es
una consola interna autenticada.

**Descartado.** Servidor Next.js independiente: exigía proxy inverso, CORS con credenciales y dos
contenedores para el mismo resultado funcional.

## D-12. Documentos originales inmutables

**Decisión.** Copia con nombre seguro bajo `storage/invoices/AAAA/MM/DD/PROVEEDOR/FACTURA/<hash>-nombre`,
SHA-256 en base de datos y deduplicación por hash. La descarga exige autenticación.

**Motivo.** Una factura es un documento probatorio. Modificarlo destruye su valor. La ruta
determinista y el hash permiten reconstruir y verificar el archivo. En Fase 4 se añadirá el
adaptador S3 conservando la misma clave.

## D-13. OCR sin proveedor: no se inventan datos

**Decisión.** Si no hay proveedor OCR configurado, la factura queda `ocr_status=not_configured` y las
líneas se introducen manualmente. La interfaz lo explica.

**Motivo.** Regla del cliente: nada simulado. Un OCR falso o un mensaje de éxito sin extracción real
sería peor que la ausencia de la función.

## D-14. IA y voz detrás de una interfaz de proveedor

**Decisión.** La Fase 5 definirá una interfaz `AIProvider` (STT, TTS, LLM) seleccionable por
configuración; el dominio no importará SDKs concretos. Ninguna acción física se ejecutará sin
confirmación humana.

**Motivo.** El cliente exige no acoplarse a un proveedor y mantener autorización humana en
operaciones críticas. La arquitectura actual ya separa dominio, API y UI para permitirlo.

## D-15. Tiempo: UTC en base de datos, Madrid en pantalla

**Decisión.** `UtcDateTime` serializa siempre con `Z`; el frontend usa `Intl` con
`Europe/Madrid`. Los límites de "hoy" se calculan en Madrid y se convierten a UTC en el servidor.

**Motivo.** Evita ambigüedad en cambios de horario y cumple el requisito de visualización en hora
española, incluso si el servidor está en otra región.

## D-16. Errores uniformes y trazabilidad por petición

**Decisión.** Formato `{"error": {"code", "message", "details"}}` y cabecera `X-Request-ID` en todas
las respuestas.

**Motivo.** La UI muestra mensajes claros sin interpretar excepciones; soporte puede cruzar una
petición con la auditoría y los logs.

## D-17. Informes CSV reales antes que PDF/Excel

**Decisión.** Exportaciones CSV UTF-8 con BOM y separador `;` (Excel español). PDF/Excel se
posponen a Fase 9.

**Motivo.** El CSV contiene todos los datos y es verificable ya. Publicar un "PDF" incompleto o una
plantilla vacía violaría la regla de no simular funcionalidad.

## D-18. Datos de demostración aislados

**Decisión.** `scripts/seed_demo.py` requiere `DEMO_MODE=true` y escribe en la base indicada
(`data/demo.db` por defecto). Nunca se ejecuta automáticamente en producción.

**Motivo.** Mezclar datos ficticios con reales es inaceptable en un sistema de inventario. El modo
demo se muestra en la barra superior para que nadie confunda el entorno.

## D-19. Pruebas contra la aplicación real

**Decisión.** pytest con `TestClient` sobre la app completa, base de datos temporal por ejecución,
un cliente por rol para evitar cookies compartidas.

**Motivo.** Pruebas de extremo a extremo detectan fallos de permisos y de serialización que los
mocks ocultan. Un `TestClient` compartido entre roles producía 403 engañosos por la cookie de sesión.

## D-20. Migraciones con Alembic desde el primer día

**Decisión.** Esquema inicial autogenerado y versionado (`e0ec52100839`); el arranque puede aplicar
migraciones (`AURORA_RUN_MIGRATIONS`). Los triggers de inmutabilidad se crean tras migrar.

**Motivo.** Cambiar un esquema en producción sin historial no es aceptable. Los triggers no los
gestiona Alembic, por lo que se aplican de forma idempotente en el bootstrap.

## D-21. Las reservas comprometen stock, pero no lo mueven

Reservar resta de `available` y suma en `reserved_quantity` de la posición exacta; la mercancía
sigue físicamente donde estaba. Solo un movimiento confirmado cambia `quantity`, de modo que el
libro inmutable sigue explicando cada unidad que sale del almacén. La caducidad se aplica en el
servidor (no es un aviso visual): cualquier lectura de stock libera las reservas vencidas, las
marca como `expired` y lo audita con actor `Sistema`. Así una reserva olvidada nunca bloquea stock
para siempre, y la liberación queda explicada aunque no la haga una persona.

## D-22. Las tareas de almacén no son movimientos

Una tarea describe trabajo y responsabilidad (quién, qué, para cuándo), pero no altera el stock.
Se separan de `StockMovement` para no duplicar la fuente de verdad ni permitir «cierre de tarea»
como sustituto de una recepción o expedición. El ciclo de vida es explícito (`pending`,
`in_progress`, `blocked`, `done`, `cancelled`), cada transición va a auditoría y las tareas
cerradas no se editan (409). El nivel 4 puede leer y completar, pero el servidor comprueba que la
tarea esté asignada a su propia ficha de empleado; la UI no es la que impone la restricción.

## D-23. Las incidencias documentan, los movimientos corrigen

Una incidencia (daño, descuadre, calidad o seguridad) es un registro de lo que pasó y de cómo se
resolvió, con severidad, responsable y transiciones explícitas. No modifica existencias: si hay que
corregir stock, se usa un movimiento auditado, de modo que el libro siga siendo la única
explicación de las cantidades. El nivel 4 puede reportar incidencias (quien está en el muelle es
quien primero ve el problema) pero no resolverlas; la resolución exige un texto mínimo y queda
auditada con el actor real. Cerrar una incidencia es un paso separado de resolverla, para que el
responsable pueda verificar la corrección antes del cierre definitivo.

## D-24. Fichajes append-only y estado calculado en el servidor

Los fichajes no se editan ni se borran: una corrección es un fichaje nuevo y auditado. El estado
de la jornada (`out`, `in`, `break`) y las horas trabajadas se derivan de la secuencia completa de
registros, nunca de un campo «estado actual» que pueda desincronizarse. Las reglas de secuencia se
validan en el servidor, incluida la compatibilidad con registros posteriores cuando un responsable
inserta un fichaje antiguo. El nivel 4 puede fichar únicamente su propia ficha; los responsables
pueden registrar fichajes ajenos (por ejemplo, una tarjeta olvidada) y queda constancia de quién lo
hizo. La planificación de turnos y las tarjetas NFC siguen pendientes y no se simulan.

## D-25. Optimización como sugerencia con geometría declarada

La base de datos guarda códigos de pasillo, estantería, nivel y posición, pero no medidas reales.
En lugar de inventar precisión, el motor de optimización usa un modelo geométrico explícito que
viaja en cada respuesta (`assumptions`): 3 m entre pasillos, 6 m entre estanterías, 1 m entre
posiciones y tiempos de picking declarados. Las recomendaciones de slotting se basan en datos
reales (salidas confirmadas, stock, capacidad y caras de picking) y explican sus motivos; no
ejecutan movimientos ni reservas. Cuando el almacén disponga de plano y tiempos medidos, solo hay
que recalibrar constantes y sustituir el orden en S por el motor que corresponda, sin cambiar el
contrato de la API ni la fuente de verdad del stock.

## D-26. Cargar un reparto es la única salida de stock

Un reparto agrupa palés precintados y no toca existencias hasta que se carga. En ese momento se
crean movimientos `shipment` confirmados por cada línea de cada palé, dentro de una sola
transacción: si un producto no tiene stock disponible (o está reservado), no se genera ningún
movimiento parcial y la carga falla con un error explicable. Los palés pasan a tránsito y se
desvinculan de la ubicación; al entregar quedan `shipped`. Un palé solo puede pertenecer a un
reparto activo, y cancelar antes de cargar lo libera, de modo que el flujo no bloquea la operación.
Después de cargar, el reparto es inmutable salvo por los hitos del transporte, que se auditan.

---

## D-27 · Copias con manifiesto y medición real de la operación

**Decisión.** La copia de seguridad la realiza `scripts/backup.py`, no una tarea manual: usa la API
de backup de SQLite o `pg_dump -Fc` para PostgreSQL, archiva el volumen de documentos y escribe un
`manifest.json` con tamaño y SHA-256 de cada pieza. Antes de dar una copia por buena se verifica
(`--verify`) y la restauración exige `--force` para no sobrescribir una base viva. La retención se
aplica sobre directorios fechados `aurora-<UTC>-<etiqueta>`.

**Por qué.** Una copia que no se ha restaurado no es una copia. El manifiesto convierte la
integridad en un dato comprobable y el mismo script sirve en local y en Docker, sin introducir
dependencias nuevas en la aplicación. Para medir el servicio se añaden dos herramientas separadas
de `pytest`: `smoke_test.py` (salud, login y lecturas de todos los módulos, más el frontend) y
`load_test.py` (usuarios concurrentes, errores, RPS y percentiles p50/p95/p99 solo con lecturas).

**Límites.** En PostgreSQL la copia depende de `pg_dump`/`pg_restore` instalados en el contenedor o
en el host; con SQLite la copia en caliente es consistente, pero el tráfico concurrente puede
introducir latencia (las cifras locales de referencia se obtuvieron con 6 usuarios y 6 s). No hay
métricas Prometheus/OpenTelemetry ni alertas automáticas: `/sistema` lo mantiene como pendiente.

---

## D-28 · Informes PDF y Excel generados en el servidor

**Decisión.** El PDF se compone con ReportLab (`LongTable` con cabecera repetida, pie con página y
totales) y el Excel con openpyxl (hoja `Resumen`, hoja de datos con cabecera fija, autofiltro,
formatos numéricos y fila de totales). Ambos reutilizan exactamente los mismos datos que el CSV:
una sola función construye el `ReportTable` y los tres formatos lo representan. El PDF limita la
maqueta a 4.000 filas y lo advierte en el subtítulo; Excel y CSV no limitan.

**Por qué.** Los informes son documentos que se archivan y se envían a terceros: deben ser reales,
reproducibles y con cifras que cuadren con la pantalla. Generarlos en el servidor evita depender de
librerías JavaScript pesadas, mantiene el control de permisos y conserva el formato español
(`1.234,500` en PDF, celdas numéricas con formato en Excel). Las dependencias se fijan en
`requirements.txt` y el contenedor las instala en la construcción.

**Límites.** No hay plantillas configurables por cliente ni envío programado por correo; el PDF es
una representación tabular, no un documento con logotipo corporativo cargado por el usuario.
Ambas cosas permanecen en la lista de pendientes de `/sistema`.

---

## D-29 · Métricas Prometheus propias, sin agente ni dependencias

**Decisión.** El backend expone `/metrics` en formato Prometheus 0.0.4 desde el propio proceso:
contador `aurora_http_requests_total` por método/ruta/estado, histograma de latencias con cubos de
5 ms a 10 s, gauge de peticiones en vuelo y gauges de base de datos, almacenamiento y operación
(palés y repartos por estado, tareas abiertas, incidencias, reservas y unidades). La etiqueta de
ruta usa la plantilla con parámetros (`/api/v1/products/{product_id}`) y agrupa el frontend como
`frontend` para que la cardinalidad no crezca con los datos. El scrape no se contabiliza.

**Por qué.** Se evita añadir `prometheus_client` o un agente lateral y se mantiene una única fuente
de verdad: el proceso que atiende las peticiones. Un `METRICS_TOKEN` opcional permite proteger el
endpoint sin acoplarlo al login de usuarios, que rompería el scrape. Las alertas se documentan como
reglas de Prometheus listas para copiar, no como una simulación dentro de la aplicación.

**Límites.** El registro es en memoria y por proceso: con varios workers de uvicorn cada uno expone
sus propias series (documentado; en Docker se usa un worker). No hay trazas OpenTelemetry ni
alertas gestionadas por AURORA; ambas cosas siguen en `/sistema` como pendientes.

---

## D-30 · Informes programados con planificador externo y SMTP propio

**Decisión.** La programación vive en la base de datos (`report_schedules`) y la ejecuta un proceso
aparte (`scripts/send_scheduled_reports.py`) pensado para cron o systemd timer, no un hilo dentro
del servidor web. Cada envío genera el informe en el momento con los mismos datos que las descargas
manuales, lo adjunta a un correo SMTP y deja `last_run_at`, `last_status`, `last_error` y la nueva
`next_run_at` en la fila. El envío manual desde la interfaz (`POST /run`) no altera la cadencia.
Sin `SMTP_HOST` no se envía ni se avanza nada: la API responde 409 `smtp_not_configured`.

**Por qué.** Un planificador externo sobrevive a reinicios, no compite con varios workers y es
fácil de operar y alertar (el script sale con código 1 si algún envío falla). Separar generación y
transporte permite probar el flujo completo con un servidor SMTP local real, sin servicios de
terceros. Los destinatarios y el contenido quedan en auditoría.

**Límites.** El correo se envía en claro salvo STARTTLS/SSL; no hay rebotes ni seguimiento de
apertura, ni plantillas corporativas configurables. La hora se guarda en UTC y el frontend la
muestra tal cual (se indica Europe/Madrid en la ayuda). Las alertas basadas en fallos de envío
dependen del orquestador (código de salida del script).

---

## D-31 · Trazas OpenTelemetry opcionales con exportador estándar

**Decisión.** La instrumentación usa los paquetes oficiales de OpenTelemetry para FastAPI y
SQLAlchemy y un `TracerProvider` con muestreo parental por ratio (20 % por defecto). Se activa con
`AURORA_TRACING_ENABLED=true`; el exportador es OTLP/HTTP (endpoint propio o variables estándar
`OTEL_EXPORTER_OTLP_*`) o consola para desarrollo. Cada respuesta con traza activa lleva
`X-Trace-ID` y se respeta el `traceparent` W3C de entrada; `/metrics` y `/healthz` quedan excluidos
para no ensuciar las trazas. Las trazas se apagan al cerrar la aplicación (flush del proveedor).

**Por qué.** Con un colector OTLP estándar (Jaeger, Tempo, Grafana Alloy…) no hay que inventar un
formato propio ni acoplar la aplicación a un proveedor. El coste es cero cuando está desactivado,
porque no se registra middleware ni se crea proveedor. El 100 % de muestreo se reserva para
depuración local; en producción se limita el volumen.

**Límites.** No se instrumenta el cliente SMTP ni trabajos externos (el planificador se ejecuta en
otro proceso y puede instrumentarse después). Sin colector configurado, el exportador OTLP falla
silenciosamente al enviar y no bloquea la aplicación. No hay propagación de baggage de negocio.

---

## D-32 · Alertas gestionadas con reglas declarativas y ciclo de vida auditable

**Decisión.** Una regla declara indicador (`open_tasks`, `overdue_tasks`, `open_incidents`,
`active_reservations`, `pending_deliveries`, `low_stock_products`, `stock_units`), operador
(`gt/gte/lt/lte`), umbral, severidad, cooldown y destinatarios opcionales. Las reglas se evalúan
con `POST /alerts/evaluate` o con `scripts.evaluate_alerts` en cron; cada cumplimiento crea una
alerta que no se duplica mientras siga abierta o reconocida y respeta el cooldown tras resolverse.
El ciclo es `open → acknowledged → resolved`, con usuario y nota en cada paso y auditoría
`alert.triggered/acknowledged/resolved`. Una regla con alertas no se borra: se pausa.

**Por qué.** Los umbrales son datos, no código: operaciones puede ajustarlos sin desplegar. Las
alertas se calculan con consultas reales a la misma base de datos que usa la operación, así que no
hay métricas inventadas ni copias desincronizadas. Reutilizar el `mailer` de la Fase 12 evita un
segundo camino de correo y permite probar con un SMTP local. El cooldown y la deduplicación evitan
tormentas de avisos cuando una condición persiste.

**Límites.** La evaluación es síncrona (cron), no hay escalado automático ni envío SMS/Slack. No se
resuelven alertas automáticamente cuando el indicador vuelve a rango: la resolución es humana para
dejar constancia. Los correos se envían en claro salvo STARTTLS/SSL y no hay reintentos: si el SMTP
falla, la alerta queda visible con `notification_error` y el operador puede resolverla o repetir el
envío. Las métricas se calculan sobre el inventario y la operación actual, sin ventanas históricas.

---

## D-33 · OCR local de facturas con revisión humana obligatoria

**Decisión.** La extracción usa RapidOCR (ONNX, modelos incluidos) para imágenes y PDF escaneados,
y la capa de texto de `pypdf` para PDF digitales; los PDF sin texto se rasterizan con PyMuPDF a
180 ppp. El parser es propio para facturas españolas (CIF, número, fechas, base, IVA, total y
líneas con cantidad/precio). El resultado es una propuesta con `confidence` calculada por cobertura
de campos y avisos explícitos; nunca se crean líneas automáticamente. Cada extracción persistida
guarda motor, método, confianza, texto y JSON, y deja auditoría.

**Por qué.** Ningún documento fiscal sale del servidor y no hay claves ni coste por página. Funciona
en el mismo contenedor sin servicios externos, y el flujo es honesto: la persona revisa antes de
afectar a stock o conciliación. La confianza por cobertura evita presentar una probabilidad
inventada del modelo.

**Límites.** La calidad depende de la resolución y del diseño del documento; un OCR perfecto no es
posible. Las líneas se reconocen por columnas numéricas al final de cada fila; tablas complejas,
notas al pie o descuentos por línea pueden requerir corrección manual. Solo se procesan las
primeras 5 páginas. El paquete OCR añade ~250 MB a la imagen Docker (ONNX + modelos + OpenCV), y
se usa `opencv-python-headless` para no necesitar X11. No se soportan DOCX, XLSX ni correo entrante.

---

## D-34 · AURORA Voice con Web Speech API y NLU local

**Decisión.** El navegador hace STT (`SpeechRecognition`, `es-ES`) y TTS (`SpeechSynthesis`,
prefiriendo voces españolas femeninas cuando existen). El audio nunca llega al servidor: solo se
envía el texto transcrito a `POST /voice/query`. El servidor interpreta intenciones con reglas
locales y consulta stock, ubicaciones, mínimos, tareas, incidencias, repartos y resumen; respeta
los permisos por intención y devuelve `data` estructurado, `confidence` y sugerencias. El proveedor
es intercambiable con `VOICE_PROVIDER`, pero el incluido es determinista y no inventa respuestas.

**Por qué.** Evita claves de terceros, coste por minuto y enviar conversaciones fuera de la empresa.
Las respuestas se calculan sobre la misma base de datos que la operación, así que son verificables.
La UI ofrece siempre entrada de texto: la voz es una comodidad, no un requisito.

**Límites.** La disponibilidad y la voz concreta dependen del navegador y del sistema operativo; en
navegadores sin Web Speech API solo funciona el texto. No hay conversación multi-turno con memoria,
ni preguntas abiertas fuera de las intenciones cubiertas (devuelve `unknown` con sugerencias). No
se guarda historial ni audio, lo que también impide auditar las consultas de voz. El NLU no es un
LLM: sinónimos y frases muy libres pueden caer en `unknown`.

---

## D-35 · Calibración explícita con regresión sobre tiempos de campo

**Decisión.** Cada almacén guarda sus pasos de pasillo, estantería y posición, tiempo base de
parada, penalización por nivel, velocidad, preparación fija y notas. Los cronometrajes de ruta se
almacenan con las ubicaciones, la distancia calculada y los segundos medidos. El ajuste usa
mínimos cuadrados `tiempo = intercepto + distancia/velocidad + paradas·tiempo_parada`, con al menos
3 muestras de distancias distintas, y publica R² y MAE. Los parámetros geométricos no se deducen
del tiempo: se miden en el plano.

**Por qué.** El modelo deja de ser una aproximación fija y pasa a ser auditable contra la realidad
del almacén. Separar geometría y tiempos evita que una regresión con pocos datos “invente” pasillos
que no existen. Las rutas muestran distancia, marcha, preparación y tiempo total, de modo que la
estimación se puede comparar con el cronómetro.

**Límites.** La regresión es lineal y con pocas muestras puede ser inestable; por eso se exigen tres
y se acotan velocidad y tiempos a rangos físicos. No se modelan atascos, esperas de carretilla,
alturas de recogida ni diferencias por operario. Las muestras se introducen a mano tras cronometrar
una ruta; no hay medición automática por sensores.

---

## D-36 · Turnos semanales por plantilla y asignación diaria

**Decisión.** Un turno es una plantilla (almacén, nombre, hora inicio/fin, días de la semana y
personas necesarias). Las asignaciones son por empleado y fecha, con unicidad y comprobación de
solape horario. El plan semanal calcula cobertura y huecos por día; las plantillas con asignaciones
no se borran, se pausan. La vista exige `workers.read` y la gestión `workers.write`.

**Por qué.** Planificar por plantilla evita duplicar horarios cada semana y mantiene el histórico de
asignaciones. Controlar solapes en el servidor impide que una persona quede en dos turnos
incompatibles. Enseñar los huecos es más útil que una cobertura agregada que oculte días sin
personal.

**Límites.** No se generan turnos rotativos automáticos ni se optimiza el reparto de personas; no
hay bolsa de horas, fichaje NFC ni firma de turno. Un turno no cruza medianoche (se rechaza el
horario invertido). Los cambios de días no se aplican si dejarían asignaciones huérfanas: hay que
retirarlas primero. La cobertura es informativa: el sistema avisa del hueco, no bloqueaguardar el
plan.


---

## D-37 · Tarjeta NFC como token opaco con hash en servidor

**Decisión.** Una tarjeta NFC es un token aleatorio (`AUR-NFC-…`, generado con `secrets`) asociado
a un único empleado. En la base de datos solo se guarda su SHA-256 y los últimos cuatro caracteres;
el token completo se devuelve **una sola vez** al emitirlo. Una tarjeta activa por empleado; para
sustituirla hay que revocarla. La lectura (`POST /nfc/tap`) valida el token, el estado de la
tarjeta y del empleado, y aplica las mismas reglas de secuencia que el fichaje web. El fichaje
queda con `source="nfc"` y etiqueta del lector.

**Por qué.** Un identificador de tarjeta legible no es un secreto; guardar el token en claro
permitiría fichar por cualquiera con acceso a la base de datos o a una copia de seguridad. El hash
hace que una copia filtrada no sirva para fichar. Mostrar el token una sola vez evita que quede en
pantallas, listados o registros de auditoría. Revocar en lugar de borrar conserva la trazabilidad.

**Límites.** El token se transmite al lector o al trabajador por un canal que el sistema no
controla; no hay criptografía en hardware ni atestación de tarjeta. No se escriben etiquetas NFC
desde el navegador ni se integra un lector USB: la API está probada con el token, pero la lectura
física queda pendiente. Una tarjeta perdida puede fichar hasta que un responsable la revoque. El
token no caduca por tiempo; se rota revocando y emitiendo otra.

---

## D-38 · Bolsa de horas calculada, nunca almacenada

**Decisión.** El saldo se calcula al consultar: tiempo fichado en el periodo menos la jornada
teórica del contrato (`employees.weekly_hours` prorrateada por días del periodo) más los ajustes
manuales. Los ajustes tienen fecha efectiva, minutos distintos de cero y motivo obligatorio, y se
auditan al crear y eliminar. Los fichajes no se editan: una corrección es un fichaje nuevo. El
periodo máximo es de 93 días y el saldo puede ser negativo (horas pendientes de compensar).

**Por qué.** Un saldo almacenado se desincroniza en cuanto se corrige un fichaje o cambia el
contrato. Calcularlo sobre el histórico inmutable hace que cualquier consulta sea reproducible y
auditable. Separar los ajustes permite justificar compensaciones sin falsear el fichaje. El
prorrateo por días evita comparar un periodo parcial contra una semana completa.

**Límites.** El contrato semanal es un único número por empleado; no hay calendario laboral,
vacaciones, festivos ni turnos rotativos que ajusten la jornada teórica. El prorrateo es lineal
(`weekly_hours × días / 7`), por lo que un festivo no se descuenta automáticamente. Los ajustes
los introduce un responsable con `attendance.manage`; no hay flujo de aprobación del trabajador.
El saldo no genera nómina ni pago: es un indicador operativo.
