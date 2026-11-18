# Despliegue y operación

AURORA se despliega como **una imagen** que contiene la API y el frontend compilado, más una base
de datos PostgreSQL. El objetivo es una cloud europea (por ejemplo, un VPS en Frankfurt, París o
Madrid) con HTTPS, copias de seguridad y actualizaciones controladas.

> **HTTPS es obligatorio**: las cookies `Secure`, el service worker de la PWA y la cámara del
> escáner (`getUserMedia`) solo funcionan en contextos seguros. En `localhost` se permite la cámara
> para desarrollo.

---

## 1. Despliegue rápido con Docker Compose

Requisitos: Docker Engine 24+ y Docker Compose v2, un dominio apuntando al servidor y un proxy TLS.

```bash
git clone <repositorio> aurora && cd aurora
cp .env.example .env
```

Edite `.env`:

```dotenv
POSTGRES_PASSWORD=<aleatoria, 32+ caracteres>
JWT_SECRET=<aleatoria, 32+ caracteres>          # openssl rand -hex 32
AURORA_ADMIN_EMAIL=admin@suempresa.es
AURORA_ADMIN_PASSWORD=<inicial fuerte>
PUBLIC_ORIGIN=https://aurora.suempresa.es
APP_PORT=8000
```

```bash
docker compose up -d --build
docker compose ps
curl -fsS http://127.0.0.1:8000/healthz
```

En el primer arranque el contenedor aplica las migraciones de Alembic, crea los triggers de
inmutabilidad, siembra los cinco roles con sus permisos y crea la cuenta administradora. No carga
datos de demostración: `DEMO_MODE=false`.

El administrador deberá cambiar la contraseña en el primer acceso; el sistema lo fuerza.

### Proxy TLS de ejemplo (Caddy)

```caddyfile
aurora.suempresa.es {
    encode zstd gzip
    reverse_proxy 127.0.0.1:8000 {
        header_up X-Forwarded-Proto {scheme}
        header_up X-Forwarded-For {remote_host}
    }
    header {
        Strict-Transport-Security "max-age=31536000; includeSubDomains"
        X-Content-Type-Options "nosniff"
        Referrer-Policy "strict-origin-when-cross-origin"
    }
}
```

Con Nginx, use `proxy_pass http://127.0.0.1:8000;` y reenvíe `Host`, `X-Forwarded-For` y
`X-Forwarded-Proto`. Uvicorn arranca con `--proxy-headers`. No publique el puerto de PostgreSQL.

---

## 2. Despliegue manual (sin Docker)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r backend/requirements.txt
npm --prefix frontend ci
npm --prefix frontend run build              # genera frontend/out

export ENVIRONMENT=production
export DATABASE_URL="postgresql+psycopg://aurora:CLAVE@127.0.0.1:5432/aurora"
export JWT_SECRET="$(openssl rand -hex 32)"
export COOKIE_SECURE=true
export AURORA_BOOTSTRAP=true
export AURORA_RUN_MIGRATIONS=true
export AURORA_ADMIN_EMAIL=admin@suempresa.es
export AURORA_ADMIN_PASSWORD='<inicial fuerte>'
export STORAGE_DIR=/var/lib/aurora/storage

cd backend
../.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers \
  --forwarded-allow-ips 127.0.0.1
```

Gestione el proceso con systemd o su supervisor. Ejemplo de unidad:

```ini
[Unit]
Description=AURORA Logistics AI
After=network.target postgresql.service

[Service]
User=aurora
WorkingDirectory=/opt/aurora/backend
EnvironmentFile=/etc/aurora/aurora.env
ExecStart=/opt/aurora/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 --proxy-headers --forwarded-allow-ips 127.0.0.1
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

---

## 3. Variables de entorno

| Variable | Obligatoria | Descripción |
|---|---|---|
| `ENVIRONMENT` | Sí | `development`, `staging` o `production` |
| `DATABASE_URL` | Sí | `postgresql+psycopg://usuario:clave@host:5432/aurora` |
| `JWT_SECRET` | Sí en producción | 32+ caracteres aleatorios; el backend rechaza el valor de desarrollo |
| `COOKIE_SECURE` | Sí en producción | `true` con HTTPS |
| `ACCESS_TOKEN_MINUTES` | No | Duración de la sesión (por defecto 480 = un turno) |
| `AURORA_BOOTSTRAP` | No | Crea esquema, triggers, roles y admin si faltan |
| `AURORA_RUN_MIGRATIONS` | No | Aplica Alembic al arrancar |
| `AURORA_ADMIN_EMAIL/PASSWORD/NAME` | Primer arranque | Cuenta administradora inicial |
| `DEMO_MODE` | No | Marca la interfaz como demostración; nunca en producción |
| `METRICS_TOKEN` | No | Si se define, `/metrics` exige `Authorization: Bearer <token>` |
| `AURORA_TRACING_ENABLED` | No | Activa trazas OpenTelemetry (`false` por defecto) |
| `AURORA_TRACING_EXPORTER` | No | `otlp` (por defecto) o `console` para desarrollo |
| `AURORA_TRACING_SAMPLE_RATIO` | No | Ratio de muestreo (0.2 por defecto) |
| `OTLP_ENDPOINT` | No | Endpoint OTLP/HTTP; vacío usa `OTEL_EXPORTER_OTLP_ENDPOINT` |
| `SMTP_HOST/PORT` | Para informes | Servidor de correo saliente (por defecto 587) |
| `SMTP_USER/PASSWORD` | No | Autenticación SMTP si el servidor la exige |
| `SMTP_FROM` | Para informes | Remitente de los informes programados |
| `SMTP_STARTTLS` / `SMTP_SSL` | No | STARTTLS activo por defecto; `SMTP_SSL=true` para puerto 465 |
| `STORAGE_DIR` | No | Ruta de documentos originales (volumen persistente) |
| `MAX_UPLOAD_MB` | No | Tamaño máximo por factura (25 por defecto) |
| `WAREHOUSE_TIMEZONE` | No | `Europe/Madrid` |
| `CORS_ORIGINS` | Solo dev | Orígenes permitidos cuando el frontend va en otro puerto |

`assert_safe()` impide arrancar en producción si `JWT_SECRET` es débil, si se usa SQLite o si
`COOKIE_SECURE` es falso.

---

## 4. Migraciones y actualizaciones

Con `AURORA_RUN_MIGRATIONS=true`, cada arranque aplica las migraciones pendientes. Para controlarlas
manualmente:

```bash
docker compose exec api alembic current
docker compose exec api alembic upgrade head
```

Procedimiento recomendado de actualización:

1. Copia de seguridad de base de datos y almacenamiento (sección 5).
2. `docker compose build` y `docker compose up -d`.
3. Verificar `/healthz` y `/api/v1/system/health`.
4. Revisar los logs (`docker compose logs -f api`).

Esta entrega añade las migraciones `8c1f4b2a7d90` (tipo de incidencia y vínculos a producto y
palé) y `d4e5f6a7b8c9` (palés asignados a repartos), además de permisos nuevos (`tasks.*`,
`incidents.report`, `attendance.clock`). Aplique el esquema con
`AURORA_RUN_MIGRATIONS=true` y arranque una vez con `AURORA_BOOTSTRAP=true` para que la semilla
RBAC cree los permisos y los asigne a los cinco roles; después puede volver a `false`. Sin ese
paso, las rutas de tareas e incidencias responderán 403 aunque el administrador tenga la sesión
abierta. Compruebe con:

```bash
docker compose exec api python -c "import app.main"   # importación sana
curl -fsS -b cookies.txt http://127.0.0.1:8000/api/v1/tasks | head -c 200
curl -fsS -b cookies.txt http://127.0.0.1:8000/api/v1/incidents | head -c 200
curl -fsS -b cookies.txt http://127.0.0.1:8000/api/v1/attendance/me | head -c 200
curl -fsS -b cookies.txt "http://127.0.0.1:8000/api/v1/optimization/slotting?days=30" | head -c 200
curl -fsS -b cookies.txt http://127.0.0.1:8000/api/v1/deliveries | head -c 200
```

Las migraciones son aditivas por diseño; aun así, pruebe siempre en staging con una copia de la
base real antes de producción.

---

## 5. Copias de seguridad y restauración

### 5.1 Copia verificable con `scripts/backup.py`

El script empaqueta en `backups/aurora-<fecha>-<etiqueta>/` la base de datos, el volumen de
documentos y un `manifest.json` con tamaños y SHA-256 de cada fichero. Con SQLite usa la API de
backup del motor (copia consistente con la base en uso); con PostgreSQL ejecuta `pg_dump -Fc`.

```bash
cd backend
../.venv/bin/python -m scripts.backup --label diaria --keep 14
../.venv/bin/python -m scripts.backup --list
../.venv/bin/python -m scripts.backup --verify backups/aurora-20261117T030000Z-diaria
```

En Docker:

```bash
docker compose exec -T api python -m scripts.backup --output /data/backups --label diaria --keep 14
```

Programe la copia a diario con cron (`0 3 * * *`) o un timer de systemd, cifre el directorio y
guárdelo fuera del servidor. La retención (`--keep`) elimina las copias más antiguas.

### 5.2 Restauración

Pare el servicio, verifique la copia y restáurela. La restauración exige `--force` si el destino
ya existe, para evitar sobrescrituras accidentales:

```bash
docker compose stop api
cd backend
../.venv/bin/python -m scripts.backup --restore backups/aurora-20261117T030000Z-diaria --force
docker compose start api
```

El script rechaza rutas inseguras dentro del tar y conserva la base anterior solo si se copia a
mano antes: haga siempre una copia del estado actual antes de restaurar.

### 5.3 Copia manual equivalente (sin el script)

**Base de datos**

```bash
docker compose exec -T db pg_dump -U aurora -Fc aurora > aurora-$(date +%F).dump
```

**Documentos originales** (volumen `aurora-storage`)

```bash
docker run --rm -v aurora_aurora-storage:/data -v "$PWD":/backup alpine \
  tar czf /backup/aurora-storage-$(date +%F).tar.gz -C /data .
```

En cualquier caso, **pruebe la restauración** al menos una vez al trimestre:

```bash
docker compose stop api
docker compose exec -T db dropdb -U aurora aurora && docker compose exec -T db createdb -U aurora aurora
cat aurora-AAAA-MM-DD.dump | docker compose exec -T db pg_restore -U aurora -d aurora --clean --if-exists
docker compose start api
```

La base de datos y los documentos son el único estado persistente: el contenedor de aplicación no
guarda nada fuera de sus volúmenes.

---

## 6. Monitorización y operación

- `GET /healthz` — liveness para el balanceador (sin base de datos).
- `GET /api/v1/system/health` — comprueba base de datos y almacenamiento.
- `X-Request-ID` en cada respuesta; los errores 5xx registran el mismo identificador en el log.
- Auditoría en `/auditoria` (nivel 1, 2 o auditor) y por SQL para investigaciones.
- Logs de la aplicación en JSON/lineal según el driver; envíe a su agregador (Loki, CloudWatch…).
- Alertas sugeridas: healthcheck fallando, errores 5xx, espacio en disco del volumen de documentos,
  intentos de login fallidos repetidos.

### Métricas Prometheus

`GET /metrics` expone el formato de texto Prometheus 0.0.4. Series principales:

- `aurora_http_requests_total{method,route,status}` y `aurora_http_request_duration_seconds`
  (histograma con cubos de 5 ms a 10 s). Las rutas usan plantilla (`{product_id}`), no ids.
- `aurora_http_requests_in_flight`, `aurora_process_start_time_seconds` y `aurora_info`.
- `aurora_database_up`, `aurora_storage_bytes`, `aurora_storage_files`.
- `aurora_pallets_total{status}`, `aurora_deliveries_total{status}`, `aurora_tasks_open`,
  `aurora_incidents_open`, `aurora_reservations_active`, `aurora_stock_units_total`.

Configure el scrape (por ejemplo en `prometheus.yml`). Si define `METRICS_TOKEN`, use la misma
credencial en `authorization`:

```yaml
scrape_configs:
  - job_name: aurora
    scrape_interval: 30s
    metrics_path: /metrics
    authorization:
      type: Bearer
      credentials: <METRICS_TOKEN>
    static_configs:
      - targets: ["aurora:8000"]
```

Reglas de alerta listas para copiar (`aurora.rules.yml`):

```yaml
groups:
  - name: aurora
    rules:
      - alert: AuroraDown
        expr: up{job="aurora"} == 0
        for: 2m
        labels: { severity: critical }
        annotations: { summary: "AURORA no responde" }
      - alert: AuroraDatabaseDown
        expr: aurora_database_up == 0
        for: 1m
        labels: { severity: critical }
        annotations: { summary: "La base de datos no responde a SELECT 1" }
      - alert: AuroraErrores5xx
        expr: |
          sum(rate(aurora_http_requests_total{status=~"5.."}[5m]))
          / clamp_min(sum(rate(aurora_http_requests_total[5m])), 0.001) > 0.02
        for: 10m
        labels: { severity: warning }
        annotations: { summary: "Más del 2 % de peticiones con error 5xx" }
      - alert: AuroraLatenciaP95
        expr: |
          histogram_quantile(0.95,
            sum by (le) (rate(aurora_http_request_duration_seconds_bucket[5m]))) > 1
        for: 10m
        labels: { severity: warning }
        annotations: { summary: "p95 por encima de 1 s durante 10 minutos" }
      - alert: AuroraDiscoDocumentos
        expr: aurora_storage_bytes > 20 * 1024 * 1024 * 1024
        for: 1h
        labels: { severity: warning }
        annotations: { summary: "El volumen de documentos supera 20 GiB" }
```

**Importante:** el registro de métricas es en memoria y por proceso. El contenedor de referencia
arranca un único worker de uvicorn; si escala horizontalmente, cada réplica expone sus propias
series y Prometheus debe rasparlas todas (no sume histogramas entre réplicas sin agregar `le`).
No hay trazas OpenTelemetry todavía.

### Informes programados por correo

Defina `SMTP_HOST`, `SMTP_FROM` y, si procede, credenciales. Sin host, la interfaz muestra la
programación como no configurada y la API rechaza el envío manual con 409.

El envío lo dispara un proceso externo (no un hilo del servidor web). Ejecútelo cada 5–10 minutos:

```cron
*/10 * * * * cd /opt/aurora/backend && ../.venv/bin/python -m scripts.send_scheduled_reports >> /var/log/aurora-reports.log 2>&1
```

Con Docker:

```bash
docker compose exec -T api python -m scripts.send_scheduled_reports
```

Compruebe antes qué está vencido y si SMTP responde:

```bash
cd backend
../.venv/bin/python -m scripts.send_scheduled_reports --dry-run
```

El script sale con código 2 si no hay SMTP configurado (sin tocar las programaciones), con 1 si
algún envío falla y con 0 si todo va bien; use ese código para alertar. Cada ejecución actualiza
`last_run_at`, `last_status`, `last_error` y `next_run_at`, y deja auditoría
`report_schedule.sent/failed`. El envío manual desde `/informes` no cambia la cadencia.

Prueba recomendada antes de producción: cree una programación con su propia cuenta, pulse
**Enviar** y confirme que el adjunto (PDF/Excel/CSV) llega y abre correctamente. El flujo completo
está cubierto por pruebas automatizadas contra un servidor SMTP local.

### Calibración y turnos

La calibración se guarda en base de datos (`warehouse_calibrations`) y los cronometrajes en
`route_time_samples`; no requiere configuración adicional. Tras medir el plano, guarde los valores
en `/optimizacion` y registre al menos tres rutas cronometradas antes de pulsar **Ajustar**. El
ajuste muestra R² y MAE: si R² es bajo, revise las muestras en lugar de aceptar el resultado.

Los turnos (`work_shifts`, `shift_assignments`) se planifican en `/turnos`. No hay proceso en
segundo plano: el plan se calcula al consultar la semana. Revise cada lunes los huecos marcados en
ámbar y asigne personal; el sistema rechaza solapes y días no planificados. Las plantillas con
asignaciones deben pausarse, no borrarse, para conservar el historial.

### OCR local de facturas

El OCR funciona dentro del contenedor: no requiere claves ni servicios externos. Compruebe el motor
tras desplegar:

```bash
curl -s -b cookies.txt https://aurora.ejemplo.es/api/v1/invoices/ocr/config
```

Debe devolver `available: true` y `external_service: false`. La imagen incluye RapidOCR (ONNX),
PyMuPDF y OpenCV headless; reserve al menos 1 GB de RAM para procesar páginas a 180 ppp y mantenga
`MAX_UPLOAD_MB` en un valor razonable (25 MB por defecto). Los documentos se procesan en un archivo
temporal que se borra al terminar; solo se persiste el original inmutable y el JSON de extracción.
Si el motor no está disponible, la API devuelve `available: false` y las líneas siguen pudiendo
introducirse a mano.

### AURORA Voice

No hay nada que configurar para usar la voz: el dictado y la lectura ocurren en el navegador del
usuario. `VOICE_PROVIDER=aurora-builtin` (por defecto) y `VOICE_LOCALE=es-ES` pueden ajustarse en
`.env`. El micrófono exige contexto seguro (HTTPS o `localhost`); en HTTP el navegador lo bloquea.
El servidor solo recibe el texto de la consulta y no guarda audio ni historial. Si el navegador no
soporta Web Speech API, la página `/voz` mantiene la entrada de texto.

### Evaluación de alertas

Las reglas se evalúan con un trabajo independiente; crear alertas es el resultado normal de una
condición real, así que el script solo sale con 1 si una regla falla al evaluarse:

```cron
*/5 * * * * cd /opt/aurora/backend && ../.venv/bin/python -m scripts.evaluate_alerts >> /var/log/aurora-alerts.log 2>&1
```

```bash
cd backend
../.venv/bin/python -m scripts.evaluate_alerts --dry-run   # ver indicadores y umbrales
../.venv/bin/python -m scripts.evaluate_alerts             # crear alertas y notificar
```

Revise el resultado en `/alertas`. Una regla sin alertas sin resolver no vuelve a avisar; tras
resolverla se respeta `cooldown_minutes` antes de crear otra. Los correos usan la misma
configuración SMTP que los informes programados (`AURORA_SMTP_*`); sin SMTP la alerta se crea con
`notification_error` y sigue visible en la aplicación. Las transiciones quedan en auditoría
(`alert.triggered/acknowledged/resolved`).

### Trazas OpenTelemetry

Active las trazas solo si hay un colector OTLP disponible:

```bash
export AURORA_TRACING_ENABLED=true
export AURORA_TRACING_EXPORTER=otlp
export AURORA_TRACING_SAMPLE_RATIO=0.2
export OTLP_ENDPOINT=http://otel-collector:4318/v1/traces
```

Cualquier colector compatible con OTLP/HTTP sirve (OpenTelemetry Collector, Grafana Alloy, Tempo,
Jaeger). Para depurar sin colector use `AURORA_TRACING_EXPORTER=console`: los spans se escriben en
el log con nombre, duración, atributos HTTP y consultas SQL. Compruebe que la respuesta incluye
`X-Trace-ID` y que el colector recibe el servicio `aurora-logistics-ai`.

Las consultas SQL se instrumentan sin comentarios añadidos al SQL; el nombre del span es la
sentencia. El planificador externo (`scripts/send_scheduled_reports.py`) no está instrumentado por
ahora: su resultado queda en la tabla de programaciones y en la auditoría.

### Prueba de humo y carga tras cada despliegue

```bash
cd backend
../.venv/bin/python -m scripts.smoke_test --base-url https://aurora.example.com \
  --email admin@aurora.demo --password 'CAMBIAR'
../.venv/bin/python -m scripts.load_test --base-url https://aurora.example.com \
  --concurrency 8 --duration 20 --max-error-rate 0.01
```

`smoke_test.py` comprueba salud, login y las lecturas de todos los módulos, más la entrega del
frontend; devuelve código 1 si algo falla. `load_test.py` mide RPS y percentiles reales solo con
lecturas y falla si supera la tasa de error indicada. Referencia medida en local (SQLite, 6
usuarios, 6 s): 471 peticiones, 0 errores, 83 req/s, p50 57 ms, p95 180 ms, p99 253 ms; en
producción con PostgreSQL los valores deben obtenerse contra el servidor real y registrarse.

### Mantenimiento

- Rotar `JWT_SECRET` invalida todas las sesiones (los usuarios vuelven a entrar). `token_version`
  permite además revocar sesiones por cuenta.
- Revisar trimestralmente las cuentas activas y los niveles en `/personal`.
- La auditoría y los movimientos no se pueden borrar ni modificar (triggers). Planifique el
  crecimiento del disco de PostgreSQL.
- El almacenamiento de facturas es append-only; la deduplicación por SHA-256 evita repetidos.

---

## 7. Checklist de seguridad antes de abrir el sistema

- [ ] HTTPS activo y redirección desde HTTP.
- [ ] `JWT_SECRET` aleatorio de 32+ caracteres, guardado en gestor de secretos.
- [ ] `COOKIE_SECURE=true` y `ENVIRONMENT=production`.
- [ ] PostgreSQL accesible solo desde la red interna; contraseña fuerte.
- [ ] Cuenta administrador inicial con contraseña nueva (el sistema lo fuerza).
- [ ] Cuentas nominales por trabajador; nadie comparte usuario.
- [ ] Nivel mínimo necesario para cada persona (nivel 5 para auditores).
- [ ] Copias automáticas verificadas y restauración probada.
- [ ] Volumen `STORAGE_DIR` con permisos restringidos y copia incluida.
- [ ] Proxy con límite de tamaño de subida acorde a `MAX_UPLOAD_MB`.
- [ ] `DEMO_MODE=false` y ninguna base de demostración en el servidor.

---

## 8. Pendiente de infraestructura (fases posteriores)

| Capacidad | Cuándo | Nota |
|---|---|---|
| Almacenamiento S3 compatible | Fase 4 | Adaptador sobre la misma clave `storage/invoices/...` |
| Redis + Celery | Fase 4+ | Tareas asíncronas, informes programados |
| OCR de facturas | Fase 4 | Proveedor externo; sin él las líneas son manuales |
| AURORA Voice (STT/TTS/LLM) | Fase 5 | Voz femenina española; proveedor intercambiable |
| Telefonía SIP/API y GPS de repartos | Fase 8 | Requiere operador, credenciales y dispositivo |
| Monitorización externa (Prometheus/OpenTelemetry) | Fase 9 | Endpoints de métricas y trazas |

Ninguna de estas piezas se simula en la entrega actual: `/sistema` muestra su estado real.
