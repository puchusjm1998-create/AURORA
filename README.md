# AURORA LOGISTICS AI

Plataforma de gestión logística para almacenes de 10–50 trabajadores. Esta entrega cubre las
**fases 1 a 7 y 9 a 14** del roadmap y la **fase 8 en su parte verificable**: GPS de reparto, firma
de entrega y registro/handoff de llamadas; la marcación automática con un proveedor SIP/API real
sigue pendiente y se identifica como tal. El recorrido operativo es recepción →
almacenamiento → localización → expedición, con inventario real, trazabilidad QR, palés,
movimientos auditados, reservas, tareas, incidencias, fichaje con pausas, turnos, tarjetas NFC,
bolsa de horas, calibración y rutas de picking, repartos, facturas, OCR, alertas, informes, voz y
panel de control.

El sistema no es una maqueta: la interfaz habla con una API FastAPI que persiste en base de datos,
valida permisos en el servidor y registra cada operación en un libro de auditoría inmutable.

- **Frontend:** Next.js 15 + TypeScript + PWA (exportación estática servida por el backend).
- **Backend:** Python 3.11+ / FastAPI + SQLAlchemy 2.
- **Base de datos:** SQLite en desarrollo y pruebas; PostgreSQL en producción.
- **Idioma y formato:** español de España, fechas en `Europe/Madrid`, almacenamiento en UTC.
- **Despliegue:** Docker y cloud europea (`docs/DEPLOYMENT.md`).

---

## 1. Qué está operativo en esta entrega

| # | Requisito de la primera entrega | Estado | Dónde |
|---|---|---|---|
| 1 | Inicio de sesión seguro | ✅ | `/login`, JWT en cookie `HttpOnly`, bloqueo por intentos |
| 2 | Panel de administración | ✅ | `/` con KPIs reales y actividad reciente |
| 3 | Gestión de productos | ✅ | `/inventario`, `/producto`, `/productos/nuevo` |
| 4 | Crear almacenes | ✅ | `/almacenes` |
| 5 | Crear ubicaciones jerárquicas | ✅ | `/almacen` (mapa + alta de posiciones) |
| 6 | Crear palés | ✅ | `/pales`, ficha en `/pale` |
| 7 | Generar códigos QR | ✅ | `/etiquetas` (hoja A4 imprimible) y en cada ficha |
| 8 | Escaneo QR desde móvil | ✅ | `/escaner` con cámara (`jsQR`) y entrada manual |
| 9 | Asociar productos y cantidades a palés | ✅ | Ficha del palé, con lote y números de serie |
| 10 | Consulta de localización exacta | ✅ | `/ubicacion`, ficha de producto y resolución de QR |
| 11 | Registro de entradas | ✅ | `/operaciones` y recepción desde factura |
| 12 | Registro de salidas | ✅ | `/operaciones` y expedición de palé |
| 13 | Historial de movimientos | ✅ | `/movimientos` con filtros y detalle |
| 14 | Base de datos persistente | ✅ | SQLite/PostgreSQL con Alembic |
| 15 | Interfaz responsive PC/tablet/Android | ✅ | PWA instalable, navegación inferior y escáner móvil |

Además: facturas con documento original inmutable, conciliación, personal y cuentas con RBAC de
5 niveles, auditoría append-only, informes CSV y página de transparencia `/sistema`.

### Capacidades de las fases 2 a 14

| Funcionalidad | Estado | Dónde |
|---|---|---|
| Reservas de stock por pedido, posición y caducidad | ✅ | `/reservas` (alta, liberación y caducidad automática) |
| Tareas de almacén con responsable, prioridad y vencimiento | ✅ | `/tareas` (crear, iniciar, completar, cancelar, reabrir) |
| Incidencias con tipo, severidad, responsable y resolución | ✅ | `/incidencias` (reportar, reconocer, resolver, cerrar, reabrir) |
| Permisos específicos de tareas, reservas e incidencias | ✅ | Semilla RBAC: nivel 4 solo ejecuta sus tareas y puede reportar incidencias |
| Fichaje de jornada con entrada, salida, pausas y resumen de horas | ✅ | `/fichaje` (personal y visión del equipo) |
| Registro manual de fichajes con auditoría | ✅ | `/fichaje` (nivel ≥ 2 con `attendance.manage`) |
| Sugerencia de ubicación y ruta de picking (estimación declarada) | ✅ | `/optimizacion` (slotting, putaway y recorrido en S) |
| Repartos con vehículos, palés y expedición real de stock | ✅ | `/repartos` y ficha `/reparto` (cargar = salida auditada) |
| Indicadores operativos en el panel | ✅ | `/` (tareas, reservas, incidencias y disponible real) |
| Copias verificables, prueba de humo y prueba de carga | ✅ | `scripts/backup.py`, `smoke_test.py`, `load_test.py` (ver `docs/DEPLOYMENT.md`) |
| Informes PDF y Excel nativos | ✅ | `/informes` (PDF paginado, Excel con resumen y totales) |
| Métricas Prometheus | ✅ | `/metrics` (HTTP, latencias, base, almacenamiento y operación) |
| Informes programados por correo | ✅ | `/informes` (cadencia, destinatarios, historial y envío con cron) |
| Trazas OpenTelemetry | ✅ | `AURORA_TRACING_ENABLED=true` (OTLP/consola, `X-Trace-ID`, SQL instrumentado) |
| Alertas gestionadas | ✅ | `/alertas` (reglas por umbral, cooldown, reconocimiento, resolución y correo) |
| OCR local de facturas | ✅ | `/facturas` (PDF/imagen, proveedor, fechas, totales y líneas; revisión humana) |
| AURORA Voice | ✅ | `/voz` (dictado y lectura del navegador; respuestas con datos reales, sin audio fuera del dispositivo) |
| Calibración del almacén | ✅ | `/optimizacion` (plano, tiempos cronometrados y regresión con R²/MAE) |
| Turnos de trabajo | ✅ | `/turnos` (plantillas semanales, cobertura exigida, asignación y solapes) |
| Tarjetas NFC para fichar | ✅ | `/tarjetas` (emisión, token mostrado una vez, revocación y lectura vía API) |
| Bolsa de horas | ✅ | `/bolsa-horas` (saldo por contrato, trabajado y ajustes) y resumen propio en `/fichaje` |
| Seguimiento GPS de repartos | ✅ | `/mi-reparto` (envío desde el navegador) y `/reparto` (última posición y distancia) |
| Firma digital de entrega | ✅ | `/mi-reparto` (firma táctil, PNG + SHA-256) y consulta en `/reparto` |
| Llamadas con handoff SIP/tel | ✅ | `/llamadas` (registro, enlaces `tel:`/`sip:`, webhook y callback del proveedor) |

### Lo que todavía no está implementado (y no se muestra como si lo estuviera)

Estas capacidades pertenecen a fases posteriores y dependen de proveedores externos. La interfaz
las identifica explícitamente:

- **LLM conversacional y voz neuronal** (Fase 5 ampliada): AURORA Voice usa la Web Speech API del
  navegador y un motor local de consultas; no hay modelo de lenguaje externo ni claves de terceros.
- **Almacenamiento S3** (Fase 4): los originales se guardan ya de forma inmutable en disco local con
  estructura y SHA-256; el adaptador S3 queda pendiente.
- **Redis/Celery** (Fase 4+): trabajos asíncronos (informes programados, notificaciones). Las
  tareas de almacén de la Fase 2 ya son reales, pero se ejecutan de forma síncrona.
- **Marcación automática con un operador SIP/API real** (Fase 8): el adaptador webhook y el
  handoff `tel:`/`sip:` son reales y están probados, pero el sandbox no tiene proveedor ni
  credenciales; sin `TELEPHONY_WEBHOOK_URL` no se origina ninguna llamada y la API responde 503.
- **GPS en segundo plano**: el navegador solo comparte ubicación mientras `/mi-reparto` está
  abierto y con permiso explícito; no hay aplicación móvil nativa ni seguimiento con la pantalla
  cerrada.
- **Notificaciones asíncronas** (Redis/Celery): las alertas y los informes ya se envían por SMTP,
  pero la evaluación corre en cron síncrono y no hay cola de trabajos.
- **Lectura física de tarjetas NFC**: la API `POST /nfc/tap` y la emisión/revocación son reales y
  están probadas, pero no se escriben etiquetas NFC desde el navegador ni se integra un lector USB;
  el token debe entregarse al trabajador o lector por un canal seguro. La tarjeta es un token
  opaco, no una tarjeta bancaria ni un certificado criptográfico en hardware.
- **Medición automática de tiempos**: los cronometrajes se introducen desde la ruta calculada; no
  hay sensores ni lectores de presencia que midan recorridos sin intervención.

---

## 2. Arranque local

Requisitos: Python 3.11+, Node.js 20+ y npm.

```bash
# 1) Dependencias del backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt

# 2) Frontend compilado (FastAPI sirve frontend/out)
npm --prefix frontend install
npm --prefix frontend run build

# 3) Base de datos + datos de demostración (aislados)
cd backend
export DATABASE_URL="sqlite:///$(pwd)/data/demo.db"
export DEMO_MODE=true
export AURORA_ADMIN_EMAIL=admin@aurora.demo
export AURORA_ADMIN_PASSWORD='Aurora2026!'
python scripts/seed_demo.py

# 4) Arranque
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Abra `http://localhost:8000`. La API interactiva está en `/api/docs`.

### Desarrollo del frontend con recarga en caliente

```bash
# Terminal 1: API
cd backend && uvicorn app.main:app --reload --port 8000

# Terminal 2: Next.js
cd frontend
NEXT_PUBLIC_API_BASE=http://localhost:8000 npm run dev
```

`CORS_ORIGINS` debe incluir `http://localhost:3000`. En producción **no** se usa
`NEXT_PUBLIC_API_BASE`: frontend y API comparten origen y la cookie es first-party.

### Cuentas de demostración

Solo existen si se ejecuta `scripts/seed_demo.py` con `DEMO_MODE=true`. Contraseña común:
`Aurora2026!` (cámbiela en cualquier entorno real).

| Correo | Nivel | Rol |
|---|---|---|
| `admin@aurora.demo` | 1 | Administrador principal |
| `logistica@aurora.demo` | 2 | Responsable de logística |
| `encargado@aurora.demo` | 3 | Encargado |
| `operario@aurora.demo` | 4 | Trabajador |
| `auditor@aurora.demo` | 5 | Auditor (solo lectura) |

Los datos de demostración viven en una base de datos separada (`data/demo.db`). Para datos reales,
use otra `DATABASE_URL` y **no** ejecute el script de demostración.

---

## 3. Estructura del repositorio

```
backend/
  app/
    core/          configuración, enums, RBAC, seguridad, errores, tiempo UTC/Madrid
    models.py      45 tablas SQLAlchemy (inventario, palés, movimientos, facturas…)
    schemas.py     DTOs Pydantic y paginación
    api/           dependencias, serializadores y rutas /api/v1
    services/      StockEngine, auditoría, secuencias, QR, OCR, calibración, turnos, NFC y bolsa de horas
    db/            bootstrap, triggers de inmutabilidad
  alembic/         migraciones versionadas
  scripts/         seed_demo.py, backup.py, smoke_test.py y load_test.py
  tests/           93 pruebas automatizadas
frontend/
  app/             rutas App Router (login y área autenticada)
  components/      design system, shell, selectores, escáner QR
  lib/             cliente API, tipos, formato es-ES, sesión y hooks
  public/          PWA: manifest, service worker, iconos
docs/
  DECISIONS.md     decisiones técnicas y por qué
  DEPLOYMENT.md    despliegue en cloud europea
  API.md           referencia de la API
```

Separación estricta: la interfaz **no** contiene lógica de negocio ni accede a la base de datos;
toda validación y cálculo de stock ocurre en `StockEngine` dentro de una transacción. El motor de
IA (fase 5) se conectará mediante una interfaz de proveedor, sin acoplar la aplicación.

---

## 4. Modelo operativo

### Códigos únicos y no reutilizables

| Entidad | Formato | Ejemplo |
|---|---|---|
| Almacén | `ALM-NN` | `ALM-01` |
| Ubicación | `ALM-01-P04-EB-N02-POS03` | pasillo, estantería, nivel, posición |
| Palé | `AUR-PAL-000001` | secuencia persistente |
| Objeto individual | `AUR-OBJ-000001` | unidad serializada |
| Producto | `AUR-SKU-000001` | SKU legible |
| Trabajador | `AUR-EMP-000001` | ficha de personal |
| Movimiento | `AUR-MOV-000001` | libro de stock |
| Factura | número del proveedor | único por proveedor |

Los QR codifican `aurora://producto/<código>`, `aurora://pale/<código>`,
`aurora://ubicacion/<código>`, `aurora://objeto/<código>` o `aurora://trabajador/<código>`.
El código legible se imprime siempre junto al QR para poder introducirlo a mano.

### Movimientos

Tipos: recepción, expedición, transferencia, reubicación, ajuste, devolución, consumo interno,
picking, carga, descarga y regularización. Cada movimiento:

1. Se crea en estado `draft` o directamente `confirmed` con confirmación física explícita.
2. Usa una `idempotency_key` única por operación: reintentar no duplica el movimiento.
3. Se aplica en una transacción que actualiza `stock_levels` (fuente única de verdad) y registra
   `movement_allocations` para saber qué posición de stock se tocó.
4. Nunca se borra: la cancelación es compensatoria y auditada.
5. Guarda UTC; la interfaz muestra `Europe/Madrid`.

### Permisos (RBAC de 5 niveles)

| Nivel | Rol | Alcance |
|---|---|---|
| 1 | Administrador principal | Todo, incluidas cuentas y configuración |
| 2 | Responsable de logística | Operaciones, facturas, informes, ajustes |
| 3 | Encargado | Recepción/expedición, palés, equipo |
| 4 | Trabajador | Escaneo y movimientos operativos |
| 5 | Auditor | Solo lectura y auditoría |

Los permisos se comprueban **siempre** en el servidor (`require_permission`). Ninguna cuenta puede
elevar su propio nivel, modificarse a sí misma, ni crear roles por encima del suyo. La UI oculta
acciones no permitidas, pero la decisión final es del backend.

### Seguridad

- Contraseñas con bcrypt (mínimo 10 caracteres, letras y números).
- Sesión JWT con `jti` revocable en `user_sessions` y `token_version`.
- Cookie `HttpOnly`, `SameSite=Lax`; `Secure` en producción.
- Bloqueo temporal tras intentos fallidos; el login fallido se audita sin revelar si el correo existe.
- Cambio de contraseña revoca el resto de sesiones.
- Originales de factura inmutables, deduplicados por SHA-256 y servidos solo a usuarios autorizados.
- `audit_logs` append-only mediante triggers de base de datos.

---

## 5. Pruebas

```bash
cd backend
../.venv/bin/python -m pytest tests -q
```

Resultado actual: **93 pruebas en verde** (autenticación/RBAC, ciclo de inventario, palés,
etiquetas, escaneo, facturas, mapa del almacén, reservas —incluida su caducidad—, tareas de
almacén, incidencias, fichaje —secuencias y resumen de horas—, optimización de ubicaciones y
rutas, repartos con expedición de stock, informes, auditoría y herramientas de operación: copia
con manifiesto SHA-256, retención y restauración, e informes PDF/Excel con contenido verificado, métricas Prometheus, envío SMTP con un servidor local de prueba, trazas OpenTelemetry, alertas
gestionadas con evaluación, reconocimiento y notificación, OCR local sobre PDF e imagen y consultas
de voz con permisos, calibración con regresión, planificación de turnos con solapes, tarjetas NFC con token de un solo
uso, bolsa de horas con ajustes justificados, GPS de reparto con filtro de saltos imposibles, firma
PNG verificada por SHA-256 y llamadas con handoff o webhook).
Las pruebas usan una base de datos SQLite
temporal por ejecución; nunca tocan datos reales.

Prueba de humo y de carga contra una instancia real (no forman parte de `pytest`):

```bash
../.venv/bin/python -m scripts.smoke_test --base-url http://127.0.0.1:8000
../.venv/bin/python -m scripts.load_test --concurrency 6 --duration 6
```

Verificación manual del flujo completo con la API en marcha:

1. Login como `operario@aurora.demo`.
2. `/escaner` → escanear el QR de una ubicación o introducir su código.
3. `/operaciones` → recepción con producto, cantidad, lote y ubicación de destino.
4. `/pales` → crear palé, añadir mercancía y precintar.
5. `/producto` → comprobar posiciones exactas y unidades.
6. `/reservas` → reservar unidades de una posición y comprobar que bajan las disponibles sin mover
   mercancía; liberar la reserva y ver el stock restaurado.
7. `/tareas` → crear una tarea asignada a un empleado, iniciarla y completarla; entrar como
   `operario@aurora.demo` y comprobar que solo ve y ejecuta las tareas asignadas a él.
8. `/incidencias` → reportar una incidencia (también como operario), reconocerla, resolverla con
   una explicación y cerrarla; comprobar que el stock no cambia y que la resolución queda auditada.
9. `/fichaje` → fichar entrada como `operario@aurora.demo`, iniciar y cerrar una pausa y fichar
   salida; comprobar el estado y las horas. Como encargado, registrar un fichaje manual y ver el
   resumen del equipo.
10. `/optimizacion` → pedir una sugerencia de ubicación para un producto con stock, calcular la
    ruta de una reserva activa y revisar el análisis de slotting; comprobar que nada se mueve solo.
11. `/repartos` → crear un reparto con vehículo, añadir un palé precintado y cargarlo; comprobar
    que el stock baja una sola vez y que el palé queda en tránsito.
12. `/operaciones` → expedición; `/movimientos` → ver el libro y confirmar el stock restante.

---

## 6. Producción

Consulte `docs/DEPLOYMENT.md` para Docker Compose, PostgreSQL, HTTPS, copias de seguridad y
healthchecks. Herramientas de operación incluidas, sin dependencias nuevas:

```bash
cd backend
../.venv/bin/python -m scripts.backup --label diaria --keep 14   # copia + manifiesto SHA-256
../.venv/bin/python -m scripts.backup --list                     # copias disponibles
../.venv/bin/python -m scripts.smoke_test --base-url https://aurora.example.com
../.venv/bin/python -m scripts.load_test --concurrency 8 --duration 20
```

Resumen del despliegue:

```bash
docker compose up -d --build
```

El contenedor compila el frontend y sirve la aplicación completa en el puerto 8000. En producción
son obligatorios `ENVIRONMENT=production`, `JWT_SECRET` aleatorio, `COOKIE_SECURE=true` y
`DATABASE_URL` de PostgreSQL. El backend se niega a arrancar con SQLite en producción o con la
clave de desarrollo.

---

## 7. Documentación

- `docs/API.md` — endpoints, errores, paginación y ejemplos.
- `docs/DECISIONS.md` — decisiones técnicas y alternativas descartadas.
- `docs/DEPLOYMENT.md` — despliegue, copias y operación.
- `/api/docs` — OpenAPI interactivo generado desde el código.
- `/sistema` — transparencia: qué está operativo y qué depende de terceros.
