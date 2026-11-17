# AURORA LOGISTICS AI

Plataforma de gestión logística para almacenes de 10–50 trabajadores. Esta entrega cubre la
**Fase 1 y la primera entrega funcional completa**: recepción → almacenamiento → localización →
expedición, con inventario real, trazabilidad QR, palés, movimientos auditados, facturas de
proveedor, personal, informes y panel de control.

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

### Lo que todavía no está implementado (y no se muestra como si lo estuviera)

Estas capacidades pertenecen a fases posteriores y dependen de proveedores externos. La interfaz
las identifica explícitamente:

- **AURORA Voice** (Fase 5): STT/TTS con voz femenina española, asistente conversacional y LLM
  intercambiable. No hay micrófono simulado.
- **OCR de facturas** (Fase 4): requiere proveedor externo; hoy las líneas se introducen y revisan
  manualmente. El estado se muestra como `not_configured`.
- **Almacenamiento S3** (Fase 4): los originales se guardan ya de forma inmutable en disco local con
  estructura y SHA-256; el adaptador S3 queda pendiente.
- **Redis/Celery** (Fase 4+): tareas asíncronas, informes programados y notificaciones.
- **Telefonía SIP/API** (Fase 8) y **repartos/fichaje** (Fase 7).
- **Informes PDF/Excel nativos** (Fase 9); los CSV actuales son reales y completos.

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
    models.py      33 tablas SQLAlchemy (inventario, palés, movimientos, facturas…)
    schemas.py     DTOs Pydantic y paginación
    api/           dependencias, serializadores y rutas /api/v1
    services/      StockEngine, auditoría, secuencias, QR, almacenamiento
    db/            bootstrap, triggers de inmutabilidad
  alembic/         migraciones versionadas
  scripts/         seed_demo.py (dataset de demostración aislado)
  tests/           34 pruebas automatizadas
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

Resultado actual: **34 pruebas en verde** (autenticación/RBAC, ciclo de inventario, palés,
etiquetas, escaneo, facturas, mapa del almacén, informes y auditoría). Las pruebas usan una base de
datos SQLite temporal por ejecución; nunca tocan datos reales.

Verificación manual del flujo completo con la API en marcha:

1. Login como `operario@aurora.demo`.
2. `/escaner` → escanear el QR de una ubicación o introducir su código.
3. `/operaciones` → recepción con producto, cantidad, lote y ubicación de destino.
4. `/pales` → crear palé, añadir mercancía y precintar.
5. `/producto` → comprobar posiciones exactas y unidades.
6. `/operaciones` → expedición; `/movimientos` → ver el libro y confirmar el stock restante.

---

## 6. Producción

Consulte `docs/DEPLOYMENT.md` para Docker Compose, PostgreSQL, HTTPS, copias de seguridad y
healthchecks. Resumen:

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
