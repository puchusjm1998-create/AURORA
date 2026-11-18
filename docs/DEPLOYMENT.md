# Despliegue y operación

AURORA se despliega como **una imagen** que contiene la API y el frontend compilado, más PostgreSQL,
Redis y los procesos worker/beat de Celery. El objetivo es una cloud europea (por ejemplo, un VPS en Frankfurt, París o
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
docker compose ps            # db, redis, voice-model, api, worker y beat
curl -fsS http://127.0.0.1:8000/healthz
```

`voice-model` descarga una sola vez el modelo Piper español (180 MB) en el volumen
`aurora-models` y verifica su SHA-256; después termina. Si `VOICE_TTS_PROVIDER` no es `piper`, el
servicio no descarga nada.

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
python backend/scripts/fetch_voice_model.py  # voz Piper local (opcional si usa Edge/OpenAI)

export ENVIRONMENT=production
export DATABASE_URL="postgresql+psycopg://aurora:CLAVE@127.0.0.1:5432/aurora"
export JWT_SECRET="$(openssl rand -hex 32)"
export COOKIE_SECURE=true
export AURORA_BOOTSTRAP=true
export AURORA_RUN_MIGRATIONS=true
export AURORA_ADMIN_EMAIL=admin@suempresa.es
export AURORA_ADMIN_PASSWORD='<inicial fuerte>'
export STORAGE_DIR=/var/lib/aurora/storage
export STORAGE_CACHE_DIR=/var/lib/aurora/cache
export VOICE_TTS_MODEL_PATH=/opt/aurora/backend/data/models/es_ES-davefx-medium.onnx

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
| `STORAGE_BACKEND` | No | `local` (por defecto) o `s3` |
| `STORAGE_DIR` | No | Ruta de documentos originales (volumen persistente) |
| `STORAGE_CACHE_DIR` | No | Caché de descargas S3 (volumen persistente) |
| `MAX_UPLOAD_MB` | No | Tamaño máximo por factura (25 por defecto) |
| `S3_BUCKET` | Con `s3` | Bucket destino; obligatorio para activar S3 |
| `S3_PREFIX` | No | Prefijo de claves (`aurora` por defecto) |
| `S3_REGION` | No | Región de firma (`eu-west-1` por defecto) |
| `S3_ENDPOINT_URL` | Para MinIO/Ceph | Vacío para AWS; p. ej. `http://minio:9000` |
| `S3_ACCESS_KEY_ID`/`S3_SECRET_ACCESS_KEY` | Para MinIO/Ceph | Credenciales IAM o de usuario del bucket |
| `S3_ADDRESSING_STYLE` | No | `path` para MinIO/Ceph, `virtual` para AWS |
| `S3_TIMEOUT` | No | Timeout de boto3 en segundos (30 por defecto) |
| `REDIS_URL` | Cola | `redis://redis:6379/0` en Compose |
| `CELERY_BROKER_URL`/`CELERY_RESULT_BACKEND` | No | Vacíos usan `REDIS_URL` |
| `CELERY_TASK_ALWAYS_EAGER` | No | `true` solo en pruebas; no usar en producción |
| `CELERY_TASK_TIME_LIMIT` | No | Límite por tarea en segundos (300 por defecto) |
| `VOICE_TTS_PROVIDER` | No | `piper` (por defecto), `edge`, `openai` o `browser` |
| `VOICE_TTS_VOICE` | No | Voz del proveedor; por defecto `es_ES-davefx-medium` |
| `VOICE_TTS_MODEL_PATH` | Con Piper | Ruta al `.onnx`; en Compose `/app/backend/data/models/es_ES-davefx-medium.onnx` |
| `VOICE_TTS_API_KEY` | Con OpenAI | Clave de la API de síntesis |
| `VOICE_TTS_MODEL`/`VOICE_TTS_BASE_URL` | No | Modelo y endpoint compatible con OpenAI |
| `VOICE_TTS_TIMEOUT` | No | Timeout del proveedor de voz (30 s) |
| `VOICE_TTS_MAX_CHARS` | No | Longitud máxima del texto (1200 por defecto) |
| `VOICE_TTS_CACHE_DIR` | No | Caché de audio por hash (volumen persistente) |
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
palé), `d4e5f6a7b8c9` (palés asignados a repartos), `c9d0e1f2a3b4` (calibración, tiempos y turnos)
`e1f2a3b4c5d6` (tarjetas NFC, bolsa de horas y `employees.weekly_hours`) y `f2a3b4c5d6e7`
(seguimiento GPS y firmas de entrega), además de permisos nuevos (`tasks.*`, `incidents.report`,
`attendance.clock`, `deliveries.track` y `calls.manage`). Aplique el esquema con
`AURORA_RUN_MIGRATIONS=true` y arranque una vez con `AURORA_BOOTSTRAP=true` para que la semilla
RBAC cree los permisos y los asigne a los cinco roles; después puede volver a `false`. Sin ese
paso, las rutas de tareas e incidencias responderán 403 aunque el administrador tenga la sesión
abierta. Compruebe con:

```bash
docker compose exec api python -c "import app.main"   # importación sana
curl -fsS -b cookies.txt http://127.0.0.1:8000/api/v1/tasks | head -c 200
curl -fsS -b cookies.txt http://127.0.0.1:8000/api/v1/incidents | head -c 200
curl -fsS -b cookies.txt http://127.0.0.1:8000/api/v1/attendance/me | head -c 200
curl -fsS -b cookies.txt http://127.0.0.1:8000/api/v1/nfc/cards | head -c 200
curl -fsS -b cookies.txt http://127.0.0.1:8000/lector/ | head -c 200
curl -fsS -b cookies.txt http://127.0.0.1:8000/api/v1/hours-bank | head -c 200
curl -fsS -b cookies.txt http://127.0.0.1:8000/api/v1/calls/config | head -c 200
curl -fsS -b cookies.txt http://127.0.0.1:8000/api/v1/deliveries/mine | head -c 200
curl -fsS -b cookies.txt "http://127.0.0.1:8000/api/v1/optimization/slotting?days=30" | head -c 200
curl -fsS -b cookies.txt http://127.0.0.1:8000/api/v1/deliveries | head -c 200
```

La Fase 8 añade telefonía configurable por entorno. Sin estas variables el modo por defecto es
`handoff`: la interfaz abre `tel:` o `sip:` en el dispositivo y el servidor no origina llamadas.

| Variable | Uso |
|---|---|
| `TELEPHONY_MODE` | `handoff` (por defecto), `webhook` o `disabled` |
| `TELEPHONY_SIP_DOMAIN` | Dominio SIP para construir `sip:<teléfono>@<dominio>` |
| `TELEPHONY_SIP_EXTENSION` | Extensión del agente que se envía al proveedor |
| `TELEPHONY_WEBHOOK_URL` | Endpoint del proveedor que origina la llamada (modo `webhook`) |
| `TELEPHONY_WEBHOOK_TOKEN` | Token Bearer opcional para ese endpoint |
| `TELEPHONY_CALLBACK_TOKEN` | Secreto obligatorio para que el proveedor confirme estados en `/api/v1/calls/callback` |
| `TELEPHONY_WEBHOOK_TIMEOUT` | Timeout en segundos (10 por defecto) |

El webhook recibe `to`, `contact_name`, `purpose`, `reference` y `extension`, y debe responder JSON
con `call_id` (o `id`/`sid`) y opcionalmente `status`. Si no responde 2xx, la llamada queda fallida
y auditada, y la API devuelve 502. Nunca se marca una llamada como cursada sin confirmación del
proveedor ni se guarda audio. El proveedor puede confirmar el estado real con
`POST /api/v1/calls/callback` enviando `X-Telephony-Token` o `Authorization: Bearer` con
`TELEPHONY_CALLBACK_TOKEN`; sin ese secreto el endpoint responde 503 y no queda abierto. Tras
actualizar, ejecute una vez con `AURORA_BOOTSTRAP=true` para
crear los permisos nuevos (`deliveries.track`, `calls.manage`) y asignarlos a los roles.

Las migraciones son aditivas por diseño; aun así, pruebe siempre en staging con una copia de la
base real antes de producción.

---

## 5. Copias de seguridad y restauración

### 5.1 Copia verificable con `scripts/backup.py`

El script empaqueta en `backups/aurora-<fecha>-<etiqueta>/` la base de datos, los documentos y un
`manifest.json` con tamaños y SHA-256 de cada fichero. Con SQLite usa la API de backup del motor
(copia consistente con la base en uso); con PostgreSQL ejecuta `pg_dump -Fc`. Con
`STORAGE_BACKEND=s3` descarga todos los objetos del bucket al tar; la restauración los vuelve a
subir con la misma clave, tipo MIME y SHA-256.

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

### 5.3 Migrar documentos locales a S3

Antes de cambiar `STORAGE_BACKEND` a `s3`, suba los documentos existentes. El script es idempotente:
compara tamaño y SHA-256 con los metadatos del objeto y no vuelve a subir lo que ya coincide.

```bash
cd backend
export STORAGE_BACKEND=s3 S3_BUCKET=aurora-docs S3_ENDPOINT_URL=... S3_PREFIX=aurora
../.venv/bin/python -m scripts.storage_migrate --dry-run
../.venv/bin/python -m scripts.storage_migrate
```

No borra el directorio local ni modifica la base de datos: las claves relativas no cambian. Si la
verificación de un fichero falla, sale con código 1 y deja el original intacto. Mantenga el volumen
local como copia hasta comprobar `/system/storage`, la descarga de una factura y una firma.

### 5.4 Copia manual equivalente (sin el script)

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
- `GET /api/v1/system/health` — comprueba la base de datos.
- `GET /api/v1/system/storage` y `/system/queue` — S3, Redis y worker en tiempo real.
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

El dictado sigue ocurriendo en el navegador (Web Speech API, `es-ES`). La síntesis puede hacerse en
el servidor con una voz neuronal local:

```bash
python backend/scripts/fetch_voice_model.py     # 180 MB, verifica SHA-256
# Voz es_ES-davefx-medium (CC0, Piper Voices); queda en backend/data/models/.
# El proveedor por defecto es piper.
```

Compruebe el estado con `curl -s -b cookies.txt .../api/v1/voice/status`: debe devolver
`tts.provider=piper`, `tts.available=true`, `tts.neural=true` y `audio_leaves_device=false`.
`POST /voice/speak` devuelve un WAV de Piper o un MP3 de Edge/OpenAI y cachea el audio por hash;
repita la misma frase y verifique `X-Voice-Cached: 1`. Para Edge TTS (`VOICE_TTS_PROVIDER=edge`,
requiere salida a `speech.platform.bing.com` y la voz `es-ES-ElviraNeural`) o OpenAI
(`VOICE_TTS_API_KEY`), ajuste también `VOICE_TTS_VOICE`.

El micrófono exige contexto seguro (HTTPS o `localhost`); en HTTP el navegador lo bloquea. El
servidor no guarda el texto de la síntesis ni historial de consultas. Si el proveedor no está
disponible, `/voz` cae a `SpeechSynthesis` del navegador y la interfaz lo indica.

### Almacenamiento S3 compatible

Con `STORAGE_BACKEND=s3`, subidas y descargas usan boto3 (firma v4). Funciona con AWS S3, MinIO,
Ceph RGW o cualquier API compatible. Ejemplo con MinIO en la misma red de Compose:

```dotenv
STORAGE_BACKEND=s3
S3_BUCKET=aurora-docs
S3_PREFIX=aurora
S3_REGION=eu-west-1
S3_ENDPOINT_URL=http://minio:9000
S3_ACCESS_KEY_ID=<usuario>
S3_SECRET_ACCESS_KEY=<clave>
S3_ADDRESSING_STYLE=path
```

El bucket debe existir y permitir `PutObject`, `GetObject`, `HeadObject`, `DeleteObject` y
`ListBucket` sobre `S3_PREFIX/*`; no se crea automáticamente. La aplicación comprueba el acceso al
arrancar `/system/storage` con `list_objects_v2`. Los documentos mantienen la misma clave relativa
que en local, el SHA-256 se conserva y la descarga se cachea en `STORAGE_CACHE_DIR`. Si el bucket
no responde, la API sigue en pie pero las subidas devuelven 503 `storage_unavailable` (no se deja
una copia local silenciosa).

### Cola Redis y Celery

Compose arranca Redis 7 con AOF, un worker con dos procesos y beat. Compruebe:

```bash
docker compose exec redis redis-cli ping                       # PONG
docker compose logs -f worker beat
curl -s -b cookies.txt https://aurora.ejemplo.es/api/v1/system/queue
curl -s -b cookies.txt -X POST https://aurora.ejemplo.es/api/v1/system/queue/ping
# use el task_id devuelto en /api/v1/system/queue/{task_id}
```

`broker_available=true` y `worker_online=true` significan cola operativa. Beat evalúa alertas y
envía informes programados cada 5 minutos; **desactive el cron síncrono anterior** para no
duplicar envíos. Para Redis gestionado use `REDIS_URL` con TLS (`rediss://`) y, si su proveedor lo
exige, `CELERY_BROKER_URL`/`CELERY_RESULT_BACKEND`. El sandbox se validó con Redis 7.2 local, no
con Sentinel, Cluster ni un servicio gestionado.

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

## 7 bis. Lector NFC y GPS en el navegador

- **Web NFC** (grabar etiquetas en `/tarjetas` y leerlas en `/lector`) solo está disponible en Chrome
  para Android y en contexto seguro: **HTTPS** o `localhost`. No funciona en Safari/iOS ni en la
  mayoría de navegadores de escritorio.
- **Lector USB HID**: muchos lectores NFC emulan un teclado. Configure el lector para escribir el
  token `AUR-NFC-…` y enviar Enter; `/lector` lo captura en el campo de token. No se instala ningún
  driver ni SDK propietario.
- El kiosco debe iniciar sesión con un usuario con `attendance.clock`; un usuario de nivel 4 solo
  puede fichar su propia tarjeta. Para un lector compartido use un usuario de nivel 2/3 responsable.
- **GPS**: `/mi-reparto` mantiene la pantalla activa con Screen Wake Lock cuando el navegador lo
  permite, envía cada 12 s en movimiento y cada 45 s parado, y muestra el recorrido. Si el móvil
  bloquea la pantalla o se cierra la pestaña, el navegador deja de enviar; no hay seguimiento en
  segundo plano sin app nativa.

## 8. Límites externos declarados

| Capacidad | Estado | Límite real |
|---|---|---|
| Almacenamiento S3 | Implementado | Probado contra la API S3 emulada por `moto`; falta validar bucket, IAM y red del clúster de destino |
| Redis + Celery | Implementado | Probado con Redis 7.2 local y worker/beat reales; TLS, Sentinel y Cluster no se probaron |
| Voz Piper local | Implementado | Modelo ONNX de 61 MB descargado aparte; voz `es_ES-davefx-medium` |
| Edge / OpenAI TTS | Implementado | El sandbox no tiene salida a sus endpoints; requieren Internet y, OpenAI, clave |
| LLM generativo | No incluido | Las intenciones se resuelven con reglas locales; no hay modelo conversacional |
| Marcación telefónica automática | Parcial | Handoff y webhook reales; falta un operador SIP/API y credenciales |
| Monitorización externa | Endpoints listos | `/metrics` y trazas OTLP; el colector y las alertas son infraestructura del cliente |

Ninguna de estas piezas se simula: `/sistema` muestra el estado real de S3, Redis, worker y TTS.
El detalle de lo que no puede cubrirse en este sandbox está también en `/api/v1/system/info`
(`pending`).
