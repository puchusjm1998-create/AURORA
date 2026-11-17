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
palé) y permisos nuevos (`tasks.*`, `incidents.report`). Aplique el esquema con
`AURORA_RUN_MIGRATIONS=true` y arranque una vez con `AURORA_BOOTSTRAP=true` para que la semilla
RBAC cree los permisos y los asigne a los cinco roles; después puede volver a `false`. Sin ese
paso, las rutas de tareas e incidencias responderán 403 aunque el administrador tenga la sesión
abierta. Compruebe con:

```bash
docker compose exec api python -c "import app.main"   # importación sana
curl -fsS -b cookies.txt http://127.0.0.1:8000/api/v1/tasks | head -c 200
curl -fsS -b cookies.txt http://127.0.0.1:8000/api/v1/incidents | head -c 200
```

Las migraciones son aditivas por diseño; aun así, pruebe siempre en staging con una copia de la
base real antes de producción.

---

## 5. Copias de seguridad y restauración

**Base de datos**

```bash
docker compose exec -T db pg_dump -U aurora -Fc aurora > aurora-$(date +%F).dump
```

**Documentos originales** (volumen `aurora-storage`)

```bash
docker run --rm -v aurora_aurora-storage:/data -v "$PWD":/backup alpine \
  tar czf /backup/aurora-storage-$(date +%F).tar.gz -C /data .
```

Programe ambas tareas a diario, cifre los archivos y guárdelos fuera del servidor con retención
definida por la empresa. **Pruebe la restauración** al menos una vez al trimestre:

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
| Telefonía SIP/API | Fase 8 | Requiere operador y credenciales |
| Repartos y fichaje | Fase 7 | Módulo móvil de rutas y control horario |

Ninguna de estas piezas se simula en la entrega actual: `/sistema` muestra su estado real.
