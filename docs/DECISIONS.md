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
