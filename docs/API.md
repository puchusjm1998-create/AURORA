# API de AURORA LOGISTICS AI

Base: `/api/v1`. Documentación interactiva generada desde el código: `/api/docs` (Swagger UI) y
`/api/redoc`. Esquema OpenAPI: `/api/openapi.json`.

## Autenticación

La sesión viaja en la cookie `aurora_session` (`HttpOnly`, `SameSite=Lax`, `Secure` en producción).
También se acepta `Authorization: Bearer <token>` para integraciones controladas.

```http
POST /api/v1/auth/login
Content-Type: application/json

{ "email": "operario@aurora.demo", "password": "Aurora2026!" }
```

Devuelve el usuario con su nivel de rol y la lista **efectiva** de permisos. El token JWT incluye
`jti`, que se valida contra `user_sessions`; cerrar sesión o cambiar la contraseña lo revoca.

| Método | Ruta | Descripción |
|---|---|---|
| POST | `/auth/login` | Inicio de sesión (bloqueo tras intentos fallidos) |
| POST | `/auth/logout` | Revoca la sesión actual |
| POST | `/auth/logout-all` | Revoca todas las sesiones de la cuenta |
| GET | `/auth/me` | Usuario autenticado y permisos |
| POST | `/auth/change-password` | Cambia la clave y revoca otras sesiones |

## Convenciones

- **Paginación:** `limit` (1–500 según recurso) y `offset`. Respuesta
  `{"items": [...], "total": 123, "limit": 50, "offset": 0}`.
- **Fechas:** ISO-8601 en UTC con sufijo `Z`. La UI las convierte a `Europe/Madrid`.
- **Decimales:** se serializan como cadena (`"12.500"`) para no perder precisión.
- **Idempotencia:** las operaciones de stock aceptan `idempotency_key`; repetir la misma clave con
  el mismo contenido devuelve el movimiento existente y **nunca** duplica stock.
- **Errores uniformes:**

```json
{
  "error": {
    "code": "insufficient_stock",
    "message": "No hay stock disponible suficiente en la ubicación de origen.",
    "details": { "available": "3.000", "requested": "5.000" }
  }
}
```

Códigos propios: `insufficient_stock` (422), `idempotency_mismatch` (409), `already_confirmed`
(409), `conflict` (409), `validation_error` (422), `forbidden` (403), `not_found` (404),
`cannot_escalate_privileges` (403), `self_modification_blocked` (403).

Cada respuesta incluye `X-Request-ID`, que coincide con el identificador de la traza y de la
auditoría para poder investigar una incidencia.

## Permisos

`require_permission(...)` se ejecuta en el servidor en todas las rutas. Niveles: 1 Administrador,
2 Responsable de logística, 3 Encargado, 4 Trabajador, 5 Auditor. Un nivel superior incluye los
permisos de los inferiores salvo las excepciones documentadas (por ejemplo, el auditor nunca
escribe). Los permisos efectivos de una cuenta se consultan en `GET /users/{id}/permissions`.

## Inventario

| Método | Ruta | Descripción |
|---|---|---|
| GET | `/products` | Buscar y filtrar por `search`, `category`, `supplier_id`, `active`, `low_stock` |
| GET | `/products/facets` | Categorías y proveedores presentes en el catálogo |
| POST | `/products` | Alta de producto (SKU opcional; se genera si falta) |
| GET | `/products/{id}` | Ficha con stock agregado (físico, reservado, disponible, tránsito) |
| PATCH | `/products/{id}` | Edición de datos maestros |
| DELETE | `/products/{id}` | Desactivación lógica; **nunca** borra histórico |
| GET | `/products/{id}/whereabouts` | Localización exacta: ubicación, palé, lote y cantidades |
| GET | `/products/{id}/units` | Unidades individuales y su estado |
| GET | `/products/by-sku/{sku}` | Resolución por SKU |
| GET | `/stock/levels` | Existencias por posición (`location_id`, `product_id`, `pallet_id`) |

Ejemplo de localización exacta:

```json
{
  "product": { "id": "...", "sku": "AUR-SKU-000004", "name": "Caja cartón..." },
  "positions": [
    {
      "location_id": "...",
      "location_code": "ALM-01-P02-EA-N02-POS03",
      "pallet_id": "...",
      "pallet_code": "AUR-PAL-000004",
      "batch_code": null,
      "available_quantity": "240.000"
    }
  ]
}
```

## Almacenes y ubicaciones

| Método | Ruta | Descripción |
|---|---|---|
| GET/POST | `/warehouses` | Listar / crear almacén |
| GET/PATCH | `/warehouses/{id}` | Consultar / modificar |
| GET | `/warehouses/{id}/layout` | Mapa por pasillo, estantería y posición con ocupación |
| GET/POST | `/locations` | Listar / crear ubicación (código generado) |
| GET | `/locations/by-code/{full_code}` | Resolver el código de una etiqueta |
| GET/PATCH | `/locations/{id}` | Consultar / modificar capacidad o etiqueta |
| GET | `/locations/{id}/qr` | Datos de la etiqueta |

Crear una ubicación:

```json
{ "warehouse_id": "...", "aisle": "P04", "rack": "EB", "level": "N02",
  "position": "POS03", "capacity_pallets": 2, "is_pick_face": false }
```

Responde con `full_code: "ALM-01-P04-EB-N02-POS03"`. Los códigos son únicos y no se reutilizan.

## Palés

| Método | Ruta | Descripción |
|---|---|---|
| GET/POST | `/pallets` | Listar (`location_id`, `status`, `search`) / crear |
| GET/PATCH | `/pallets/{id}` | Consultar / modificar notas o peso |
| GET | `/pallets/by-code/{code}` | Resolver QR |
| POST | `/pallets/{id}/items` | Añadir mercancía (crea recepción confirmada) |
| DELETE | `/pallets/{id}/items/{item_id}?destination_location_id=...` | Retirar mercancía a otra ubicación (movimiento interno) |
| POST | `/pallets/{id}/seal` | Precintar (`open → sealed`) |
| POST | `/pallets/{id}/move` | Reubicar (valida capacidad y escribe movimientos) |
| POST | `/pallets/{id}/ship` | Expedir (`sealed → shipped`) y descontar stock |
| GET | `/pallets/{id}/movements` | Historial del palé |

Reglas verificadas: no se añade mercancía a un palé precintado o expedido; no se expide dos veces
(409); la retirada de mercancía exige destino para no dejar stock huérfano.

## Movimientos

| Método | Ruta | Descripción |
|---|---|---|
| GET | `/movements` | Historial filtrable: tipo, estado, fechas, producto, ubicación, palé, búsqueda |
| GET | `/movements/{id}` | Detalle con `allocations` y `unit_codes` |
| POST | `/movements` | Registrar (borrador o confirmado) |
| POST | `/movements/{id}/confirm` | Confirmar borrador |
| POST | `/movements/{id}/cancel` | Cancelar con motivo (compensatorio, nunca borra) |
| GET | `/movements/meta/types` | Catálogo de los 11 tipos |

```json
{
  "movement_type": "reception",
  "product_id": "...",
  "quantity": "12.000",
  "to_location_id": "...",
  "invoice_id": "...",
  "invoice_line_id": "...",
  "reason": "Recepción factura FAC-2026-001",
  "document_ref": "FAC-2026-001",
  "confirm": true,
  "physical_confirmed": true,
  "idempotency_key": "recepcion-20261117-0001"
}
```

Tipos: `reception`, `shipment`, `transfer`, `relocation`, `adjustment`, `return`, `internal_consumption`,
`picking`, `loading`, `unloading`, `regularization`. El ajuste y la regularización requieren nivel ≤ 2.

## Reservas

| Método | Ruta | Descripción |
|---|---|---|
| GET | `/reservations` | Lista paginada (`status`, `product_id`, `reference`, `limit`, `offset`) |
| POST | `/reservations` | Reservar cantidad disponible en una posición exacta (201) |
| POST | `/reservations/{id}/release` | Liberar reserva activa (409 si ya no lo está) |

Cuerpo de alta: `product_id`, `location_id`, `pallet_id` (opcional), `quantity`, `reference` y
`expires_at` (opcional, debe ser futura). La reserva descuenta de `available` pero no mueve
mercancía física; el stock reservado se muestra en la ficha del producto y en las posiciones.

La caducidad la aplica el servidor: al leer reservas, posiciones o el panel, toda reserva activa
con `expires_at` vencido se libera, pasa a `expired` y deja rastro en auditoría con actor
`Sistema (caducidad de reserva)`. Permisos: `reservations.read` (nivel ≥ 3) y
`reservations.write` (nivel ≥ 3).

## Tareas de almacén

| Método | Ruta | Descripción |
|---|---|---|
| GET | `/tasks` | Lista paginada (`status` CSV, `assigned_to`, `mine`, `priority`, `search`) |
| GET | `/tasks/{id}` | Detalle con responsable y autor |
| POST | `/tasks` | Crear tarea (201) |
| PATCH | `/tasks/{id}` | Editar título, descripción, prioridad, responsable o vencimiento |
| POST | `/tasks/{id}/start` | Pasar a `in_progress` |
| POST | `/tasks/{id}/complete` | Cerrar como `done` (solo si está abierta) |
| POST | `/tasks/{id}/cancel` | Cancelar (409 si ya está cerrada) |
| POST | `/tasks/{id}/reopen` | Reabrir una tarea cerrada a `pending` |

Estados: `pending`, `in_progress`, `blocked`, `done`, `cancelled`. Código legible `AUR-TSK-*`.
Cada transición se audita (`task.created`, `task.updated`, `task.started`, `task.completed`,
`task.cancelled`, `task.reopened`). Una tarea **no** mueve stock: documenta el trabajo y su
responsable; la mercancía se mueve con movimientos confirmados.

RBAC: niveles 1–3 tienen `tasks.read`, `tasks.write` y `tasks.complete`; el nivel 4 (trabajador)
solo `tasks.read` y `tasks.complete`, y únicamente sobre tareas asignadas a su ficha de empleado
(si no tiene ficha vinculada o la tarea es de otra persona, la respuesta es 403). El nivel 5
(auditor) solo lee. `PATCH` sobre una tarea cerrada devuelve 409 `task_closed`.

## Incidencias

| Método | Ruta | Descripción |
|---|---|---|
| GET | `/incidents` | Lista paginada (`status` y `severity` CSV, `incident_type`, `assigned_to`, `search`) |
| GET | `/incidents/{id}` | Detalle con producto, ubicación, palé, autor y responsable |
| POST | `/incidents` | Registrar incidencia (201) |
| PATCH | `/incidents/{id}` | Editar mientras no esté cerrada (409 `incident_closed`) |
| POST | `/incidents/{id}/acknowledge` | `open` → `acknowledged` |
| POST | `/incidents/{id}/resolve` | `open`/`acknowledged` → `resolved`; requiere `resolution` |
| POST | `/incidents/{id}/close` | `resolved` → `closed` |
| POST | `/incidents/{id}/reopen` | `resolved`/`closed` → `open`; limpia la resolución |

Tipos: `damage`, `discrepancy`, `quality`, `safety`, `other`. Severidades: `low`, `medium`, `high`,
`critical`. Estados: `open`, `acknowledged`, `resolved`, `closed`; código legible `AUR-INC-*`.
Las transiciones inválidas devuelven 409 `invalid_transition`. Cada paso se audita
(`incident.created`, `incident.updated`, `incident.acknowledged`, `incident.resolved`,
`incident.closed`, `incident.reopened`). Una incidencia **no** ajusta stock: la corrección se hace
con un movimiento auditado.

RBAC: niveles 1–3 tienen `incidents.read` y `incidents.write`; el nivel 4 (trabajador) tiene
`incidents.read` y `incidents.report`, por lo que puede reportar incidencias pero no reconocerlas,
resolverlas ni cerrarlas. El nivel 5 solo lee.

## Fichaje y jornada

| Método | Ruta | Descripción |
|---|---|---|
| GET | `/attendance/me` | Estado propio, fichajes de hoy, minutos trabajados y semana (`day` opcional) |
| GET | `/attendance` | Lista paginada (`employee_id`, `event_type`, `date_from`, `date_to`) |
| GET | `/attendance/summary` | Horas por trabajador (`date_from`, `date_to`, máx. 93 días) |
| POST | `/attendance` | Registrar fichaje (201) |

Eventos: `clock_in`, `clock_out`, `break_start`, `break_end`. Estados derivados por el servidor:
`out` (fuera de turno), `in` (trabajando) y `break` (en pausa). Secuencias inválidas (fichar salida
sin entrada, dos entradas seguidas, pausa ya iniciada…) devuelven 409
`invalid_attendance_sequence`, y también se valida la compatibilidad con fichajes posteriores
cuando un responsable inserta un registro antiguo.

El registro es append-only: no hay edición ni borrado; una corrección es un fichaje nuevo. Cada
alta se audita (`attendance.recorded`) con el usuario que la realizó. Las horas se calculan en
`Europe/Madrid` con los tramos de trabajo y pausa reales.

RBAC: `attendance.read` (niveles 1–3 y auditor), `attendance.manage` (niveles 1–2) y
`attendance.clock` (niveles 1–4). El nivel 4 solo puede fichar su propia ficha; si intenta fichar
por otra persona recibe 403. El auditor no ficha.

## Optimización de ubicaciones y rutas

| Método | Ruta | Descripción |
|---|---|---|
| GET | `/optimization/putaway` | Sugerencia de ubicación (`product_id`, `pallets`, `limit`) |
| POST | `/optimization/picking-route` | Ruta de picking por reserva o por lista de ubicaciones |
| GET | `/optimization/slotting` | Análisis de rotación/ubicación (`days`, `limit`) |

`picking-route` acepta **solo una** de estas fuentes: `reservation_reference` (reserva activa) o
`location_ids` (máx. 50). También admite `return_to_dispatch`. La ruta se ordena con barrido en S:
pasillos ascendentes y posiciones alternando sentido.

El modelo geométrico es explícito y se devuelve en `assumptions`: 3,0 m entre pasillos, 6,0 m entre
estanterías, 1,0 m entre posiciones, 25 s base por parada y 6 s por nivel por encima del primero.
Las sugerencias de ubicación puntúan consolidación del mismo producto, cara de picking para alta
rotación, huecos parciales, nivel y distancia al muelle. **Nada se mueve, reserva ni modifica
automáticamente**; se requiere `inventory.read` y el movimiento posterior se hace por
`/movements`.

## Repartos y vehículos

| Método | Ruta | Descripción |
|---|---|---|
| GET/POST | `/vehicles` | Listar y crear vehículos (matrícula única) |
| PATCH | `/vehicles/{id}` | Editar modelo, capacidad o estado |
| GET | `/deliveries` | Lista paginada (`status` CSV, `search`, fechas, `limit`, `offset`) |
| GET | `/deliveries/{id}` | Detalle con palés, líneas, vehículo y conductor |
| POST | `/deliveries` | Crear reparto en borrador (201) |
| PATCH | `/deliveries/{id}` | Editar solo en `draft`/`preparing` |
| POST | `/deliveries/{id}/pallets` | Añadir palé precintado (201) |
| DELETE | `/deliveries/{id}/pallets/{pallet_id}` | Quitar palé antes de cargar |
| POST | `/deliveries/{id}/prepare` | `draft` → `preparing` |
| POST | `/deliveries/{id}/ready` | `preparing` → `ready` (exige palés) |
| POST | `/deliveries/{id}/load` | `ready` → `loaded`: genera las salidas de stock |
| POST | `/deliveries/{id}/dispatch` | `loaded` → `in_transit` con `departed_at` |
| POST | `/deliveries/{id}/deliver` | `in_transit` → `delivered`; palés `shipped` |
| POST | `/deliveries/{id}/fail` | `in_transit` → `failed` con motivo obligatorio |
| POST | `/deliveries/{id}/cancel` | Cancelar antes de cargar y liberar palés |
| DELETE | `/deliveries/{id}` | Eliminar un borrador |

El efecto sobre el stock ocurre **una sola vez, al cargar**: por cada producto de cada palé se crea
un movimiento `shipment` confirmado y físico con `document_ref` igual a la referencia del reparto.
El palé pasa a `in_transit` y se desvincula de su ubicación. Si falta stock o está reservado, la
carga falla entera (sin dejar movimientos parciales). Un palé solo puede estar en un reparto activo
a la vez; al cancelar el reparto se libera. Todo se audita (`delivery.created`, `pallet_added`,
`loaded`, `dispatched`, `delivered`, `failed`, `cancelled`).

RBAC: `deliveries.read` (niveles 1–3 y auditor) y `deliveries.write` (niveles 1–3). El nivel 4 no
gestiona repartos.

## Facturas y conciliación

| Método | Ruta | Descripción |
|---|---|---|
| GET/POST | `/invoices` | Listar / subir (multipart: `number`, `invoice_date`, `supplier_id`, `notes`, `file`) |
| GET/PATCH | `/invoices/{id}` | Consultar / cabecera |
| GET | `/invoices/{id}/file` | Descargar original (autenticado) |
| POST | `/invoices/{id}/lines` | Añadir línea (producto opcional) |
| DELETE | `/invoices/{id}/lines/{line_id}` | Eliminar línea sin recepciones |
| POST | `/invoices/{id}/reconcile` | Conciliar cantidades facturadas vs recibidas |
| GET | `/invoices/ocr/config` | Estado del motor OCR local y formatos admitidos |
| POST | `/invoices/ocr/preview` | Multipart `file`: extrae campos y líneas sin registrar nada |
| POST | `/invoices/{id}/extract` | Procesa el original guardado y persiste la extracción |
| POST | `/invoices/{id}/lines/bulk` | Añade hasta 100 líneas revisadas en lote |
| GET | `/invoices/{id}/ocr-status` | Estado del OCR de la factura |

`POST /invoices` acepta además `lines_json` (lista revisada) y `ocr_reviewed=true` para crear la
factura con las líneas propuestas por el OCR; el documento original se conserva intacto.

El OCR es **local** (RapidOCR ONNX): los PDF con capa de texto se leen directamente; los escaneados
y las imágenes se rasterizan a 180 ppp y se procesan sin salir del servidor. Devuelve proveedor,
CIF, número, fechas, base, IVA, total y líneas, con `confidence` calculada por cobertura de campos
y avisos cuando falta algo o la suma no coincide. Nunca crea líneas por sí solo: la persona revisa
y confirma. Cada extracción guardada queda en `invoice_extractions` y en auditoría
(`invoice.ocr_completed`).

El original se guarda en `storage/invoices/AAAA/MM/DD/PROVEEDOR/FACTURA/<sha256[:12]>-NOMBRE`, se
deduplica por SHA-256 y nunca se modifica. La conciliación marca `reconciled` o `discrepancy` y
`review_required` por línea; no ajusta stock por sí sola.

## Escaneo y etiquetas QR

| Método | Ruta | Descripción |
|---|---|---|
| GET | `/scan/resolve?code=` | Resuelve QR o código legible y devuelve `kind`, `title`, `href`, `extra` |
| GET | `/scan/parse?code=` | Valida el formato `aurora://tipo/código` |
| GET | `/qr?payload=&box_size=` | Imagen PNG del QR |
| GET | `/qr/labels/{kind}/{entity_id}` | Datos de etiqueta (`product`, `pallet`, `unit`, `location`, `employee`) |

El escaneo se procesa localmente en el dispositivo; solo se envía el código resuelto. Tipos:
`aurora://producto/<sku>`, `aurora://pale/<code>`, `aurora://ubicacion/<code>`,
`aurora://objeto/<code>`, `aurora://trabajador/<code>`.

## Personal y usuarios

| Método | Ruta | Permiso |
|---|---|---|
| GET | `/employees` | `workers.read` |
| POST / PATCH | `/employees` | `workers.write` |
| GET | `/roles` | `roles.manage` o nivel 1 |
| GET / POST | `/users` | `users.manage` |
| PATCH | `/users/{id}` | `users.manage` |
| POST | `/users/{id}/reset-password` | `users.manage` |
| GET | `/users/{id}/permissions` | `users.manage` |

Crear usuario requiere `email`, `full_name`, `password`, `role_level` y, opcionalmente,
`employee_id` y `must_change_password`. No se puede asignar un nivel superior al propio, ni
desactivar la propia cuenta.

## Panel, auditoría e informes

| Método | Ruta | Descripción |
|---|---|---|
| GET | `/dashboard` | KPIs (incluye tareas abiertas/vencidas, reservas activas e incidencias abiertas/críticas), ocupación, top productos, stock bajo y actividad reciente |
| GET | `/audit` | Auditoría filtrable (`action`, `entity_type`, `actor`, fechas) |
| GET | `/reports/summary` | Valoración por categoría (coste, venta, margen) |
| GET | `/reports/inventory.csv` | Inventario detallado (UTF-8 con BOM, separador `;`) |
| GET | `/reports/inventory.pdf` | Inventario en PDF A4 apaisado, cabecera repetida y totales |
| GET | `/reports/inventory.xlsx` | Inventario en Excel con hoja Resumen, autofiltro y totales |
| GET | `/reports/movements.csv` | Libro de movimientos (`date_from`, `date_to`) |
| GET | `/reports/movements.pdf` | Movimientos en PDF paginado (máximo 4.000 filas maquetadas) |
| GET | `/reports/movements.xlsx` | Movimientos en Excel nativo, fechas y cantidades numéricas |
| GET | `/reports/invoices.csv` | Facturación (`date_from`, `date_to`, `status`) |
| GET | `/reports/invoices.pdf` | Facturación en PDF con importes, estado y conciliación |
| GET | `/reports/invoices.xlsx` | Facturación en Excel con hoja Resumen y totales |
| GET | `/reports/deliveries.csv` | Repartos (`date_from`, `date_to`, `status`) con destino, conductor y firma |
| GET | `/reports/deliveries.pdf` | Repartos en PDF paginado |
| GET | `/reports/deliveries.xlsx` | Repartos en Excel nativo |
| GET | `/reports/employees.csv` | Plantilla (`active_only`): puesto, jornada, estado y cuenta |
| GET | `/reports/employees.pdf` | Plantilla en PDF |
| GET | `/reports/employees.xlsx` | Plantilla en Excel con total de jornada semanal |
| GET | `/reports/incidents.csv` | Incidencias (`date_from`, `date_to`, `status`, `severity`, `limit`) |
| GET | `/reports/incidents.pdf` | Incidencias en PDF: tipo, severidad, ubicación, responsable y resolución |
| GET | `/reports/incidents.xlsx` | Incidencias en Excel nativo |
| GET | `/reports/audit.csv` | Auditoría (`date_from`, `date_to`, `action`, `entity_type`, `actor`, `limit`) |
| GET | `/reports/audit.pdf` | Auditoría en PDF sin los JSON de cambios, para revisión |
| GET | `/reports/audit.xlsx` | Auditoría en Excel con columnas antes/después |

`limit` está acotado a 20.000 filas (5.000 por defecto) para que una exportación no agote memoria.
Los tres informes de auditoría exigen **a la vez** `reports.export` y `audit.read`: un responsable
con exportación de informes no puede descargar la auditoría si su rol no la tiene.
Los filtros de fecha de facturas usan `invoice_date` (formato `AAAA-MM-DD`); los de repartos,
`created_at` en ISO-8601 UTC. Todos los informes requieren `reports.export`. El CSV incluye BOM y
separador `;`; PDF y Excel comparten los datos y el formato español de números y fechas.

### Informes programados

| Método | Ruta | Descripción |
|---|---|---|
| GET | `/report-schedules` | Lista paginada (`active`, `search`, `limit`, `offset`) |
| POST | `/report-schedules` | Crea una programación (201) |
| PATCH | `/report-schedules/{id}` | Modifica nombre, informe, formato, cadencia, hora, destinatarios o estado |
| DELETE | `/report-schedules/{id}` | Elimina la programación (204) |
| POST | `/report-schedules/{id}/run` | Genera y envía ahora; no altera el próximo envío |
| GET | `/report-schedules/config` | Estado de SMTP, programaciones activas y vencidas |

### Alertas gestionadas (`incidents.read` / `incidents.write`)

| Método | Ruta | Descripción |
|---|---|---|
| GET | `/alerts/rules` | Reglas (`active`, `search`, paginación) |
| POST | `/alerts/rules` | Crea una regla (201) |
| PATCH | `/alerts/rules/{id}` | Modifica nombre, indicador, umbral, severidad, cooldown o correos |
| DELETE | `/alerts/rules/{id}` | Elimina la regla solo si no generó alertas (204; 409 `rule_has_alerts`) |
| GET | `/alerts` | Alertas paginadas (`status`, `severity`, `rule_id`, `search`) |
| GET | `/alerts/metrics` | Valor actual de los 7 indicadores vigilados |
| POST | `/alerts/evaluate` | Evalúa las reglas activas ahora y devuelve las alertas nuevas |
| POST | `/alerts/{id}/acknowledge` | Reconoce una alerta abierta (`note` opcional) |
| POST | `/alerts/{id}/resolve` | Resuelve una alerta abierta o reconocida (`note` opcional) |

Indicadores: `open_tasks`, `overdue_tasks`, `open_incidents`, `active_reservations`,
`pending_deliveries`, `low_stock_products` (productos cuyo stock total está bajo mínimo) y
`stock_units`. Operadores: `gt`, `gte`, `lt`, `lte`. Severidades: `info`, `warning`, `critical`.
Estados: `open`, `acknowledged`, `resolved`. Una regla con alerta sin resolver no duplica avisos;
el cooldown evita repeticiones tras resolverla. Si la regla tiene `notify_emails` y SMTP está
configurado, el correo sale al detectar la alerta; si no, la alerta persiste con
`notification_error`. Transiciones inválidas devuelven 409 `invalid_transition`.

Permiso `reports.export`. Cadencias `daily`, `weekly` (requiere `weekday` 0-6, 0 = lunes) y
`monthly` (requiere `day_of_month` 1-28); `hour_utc` 0-23. Entre 1 y 20 destinatarios validados.
Sin `SMTP_HOST`, `POST /run` responde 409 `smtp_not_configured` y no modifica la programación.
El planificador `scripts/send_scheduled_reports.py` envía los vencidos, registra el resultado y
avanza la fecha; si un envío falla, guarda `last_error`, avanza la cadencia y continúa con el resto.

Los informes PDF y Excel exigen `reports.export` igual que el CSV. Si el PDF supera 4.000 filas,
el subtítulo lo indica y remite al Excel/CSV para el detalle completo; nunca se recorta en silencio.
El Excel incluye hoja `Resumen` con fecha de generación, filtros y número de filas.

La auditoría es append-only: triggers de base de datos rechazan `UPDATE` y `DELETE` sobre
`audit_logs`, y también la eliminación de movimientos de stock.

## Sistema

| Método | Ruta | Descripción |
|---|---|---|
| GET | `/system/info` | Versión, entorno, zona horaria, fase, implementado y pendiente |
| GET | `/system/health` | Comprobación de base de datos |
| GET | `/system/storage` | Backend local/S3, bucket, endpoint, prefijo y accesibilidad real |
| GET | `/system/queue` | Redis, disponibilidad del broker y worker, modo eager y mensaje |
| POST | `/system/queue/ping` | Encola `aurora.ping` (`settings.manage`) y devuelve `task_id` |
| GET | `/system/queue/{task_id}` | Estado Celery, resultado o error de la tarea |

`/healthz` (fuera de `/api`) es el endpoint ligero para balanceadores y contenedores.

### Almacenamiento y cola

`GET /system/storage` requiere `inventory.read` y devuelve
`{backend, bucket, prefix, endpoint, reachable, error}`. Con `STORAGE_BACKEND=local` el bucket es
`null` y `reachable` es `true`; con `s3`, el backend ejecuta `list_objects_v2` para comprobar que el
bucket y las credenciales funcionan. Un error de S3 no tumba la API: se devuelve `reachable=false`
con el motivo, y las subidas fallan con 503 `storage_unavailable` sin dejar el fichero local.

Los originales de factura, las firmas de entrega y cualquier documento usan la misma clave
relativa en los dos backends. La descarga desde S3 se cachea en `STORAGE_CACHE_DIR` y se sirve con
las mismas comprobaciones de permisos y cabeceras de integridad. La caché solo se lee; borrar un
objeto del bucket produce 404 `file_missing`.

`GET /system/queue` requiere `inventory.read`. `POST /system/queue/ping` y la consulta de estado
requieren `settings.manage` (nivel 1). Sin Redis, el ping devuelve 503 `queue_unavailable`; con el
broker disponible pero sin worker, la tarea permanece `PENDING` y se puede consultar. En modo
`CELERY_TASK_ALWAYS_EAGER=true` la tarea se ejecuta en el proceso y el resultado queda en memoria
(solo para pruebas). El worker y beat se arrancan con:

```bash
celery -A app.worker.celery_app worker --loglevel=info --concurrency=2
celery -A app.worker.celery_app beat --loglevel=info
```

Beat evalúa alertas y envía informes programados cada 5 minutos. No ejecute a la vez el cron
síncrono de versiones anteriores.

Con `AURORA_TRACING_ENABLED=true`, cada respuesta incluye `X-Trace-ID` (32 hex) y se acepta el
contexto W3C `traceparent` entrante; las peticiones y consultas SQL se exportan por OTLP o consola.

`GET /metrics` (fuera de `/api`, formato Prometheus 0.0.4) expone contadores y latencias HTTP,
base de datos, almacenamiento y gauges de operación (palés, repartos, tareas, incidencias,
reservas y unidades). Si `METRICS_TOKEN` está definido, exige `Authorization: Bearer <token>`;
en caso contrario debe limitarse el acceso por red. El propio scrape no se contabiliza.

## Calibración y tiempos medidos

| Método | Ruta | Descripción |
|---|---|---|
| GET | `/optimization/calibration` | Parámetros vigentes, métricas del ajuste y últimas muestras |
| PUT | `/optimization/calibration` | Guarda plano y tiempos manuales (`locations.write`) |
| POST | `/optimization/calibration/fit` | Ajuste por mínimos cuadrados con las rutas cronometradas |
| POST | `/optimization/time-studies` | Registra una ruta y su tiempo real; calcula la distancia con el modelo vigente |
| DELETE | `/optimization/time-studies/{id}` | Elimina una muestra (no recalcula el ajuste hasta repetirlo) |

Las rutas de picking incluyen `total_walk_seconds`, `total_estimated_seconds`, `setup_seconds` y el
bloque `calibration` con almacén, método, muestras, R² y MAE. El ajuste necesita **al menos 3
muestras con distancias distintas**; si no, devuelve 422 `insufficient_samples`. La regresión estima
velocidad, tiempo de parada y preparación fija; las distancias del plano se editan a mano porque no
se pueden deducir del tiempo.

## Turnos de trabajo

| Método | Ruta | Descripción |
|---|---|---|
| GET | `/shifts` | Plantillas del almacén (`warehouse_id`, `include_inactive`) |
| POST | `/shifts` | Crea una plantilla (`workers.write`) |
| PATCH | `/shifts/{id}` | Horario, días, cobertura, nombre o pausa |
| DELETE | `/shifts/{id}` | Solo si no tiene asignaciones (409 `shift_has_assignments`) |
| GET | `/shifts/plan` | Plan por fechas (`date_from`, `date_to`, máximo 62 días) |
| POST | `/shifts/{id}/assignments` | Asigna una persona a una fecha |
| DELETE | `/shifts/{id}/assignments/{assignment_id}` | Retira la asignación |

Los días van de 0 (lunes) a 6 (domingo). Se rechazan horarios invertidos (422
`invalid_shift_hours`), asignaciones en días no planificados (422 `weekday_not_scheduled`),
duplicados (409 `duplicate_assignment`) y solapes del mismo empleado (409 `shift_overlap`).
El plan indica `assigned_count`, `missing` y `uncovered_shifts`; la cobertura se controla por
plantilla y día, sin ocultar los huecos.

## Tarjetas NFC

| Método | Ruta | Descripción |
|---|---|---|
| GET | `/nfc/cards` | Lista tarjetas (`employee_id`, `status`, paginación); nunca devuelve el token |
| POST | `/nfc/cards` | Emite una tarjeta (`attendance.manage`); el token se muestra una sola vez |
| GET | `/nfc/cards/{id}` | Consulta una tarjeta sin token |
| POST | `/nfc/cards/{id}/revoke` | Revoca la tarjeta; deja de fichar de inmediato |
| DELETE | `/nfc/cards/{id}` | Elimina una tarjeta ya revocada |
| POST | `/nfc/tap` | Ficha leyendo el token (`attendance.clock`); `action` = `auto`, `clock_in`, `clock_out`, `break_start` o `break_end` |
| GET | `/nfc/state/{employee_id}` | Estado derivado (`out`/`in`/`break`) del trabajador |

El token tiene el formato `AUR-NFC-…`; en la base de datos solo queda SHA-256 y los últimos cuatro
caracteres. El frontend `/tarjetas` graba el token en una etiqueta NDEF con Web NFC y `/lector`
acepta tanto Web NFC como un lector USB en modo teclado (token + Enter). La lectura exige HTTPS
(o localhost) y un navegador con Web NFC; el lector USB no necesita API del navegador. Hay una tarjeta activa por trabajador (409 `employee_has_active_card`). Una tarjeta
revocada devuelve 409 `card_revoked`; un token desconocido, 404. `auto` elige la transición natural
(entrada si está fuera, salida si trabaja, fin de pausa si está en pausa) y cualquier secuencia
inválida devuelve 409 `invalid_sequence`. El trabajador de nivel 4 solo puede usar su propia
tarjeta (403 si no). Cada lectura crea un fichaje append-only con `source="nfc"` y se audita.

## Bolsa de horas

| Método | Ruta | Descripción |
|---|---|---|
| GET | `/hours-bank` | Saldo por trabajador y totales (`date_from`, `date_to`, máx. 93 días) |
| GET | `/hours-bank/me` | Saldo propio (cualquier usuario con `attendance.clock` y ficha) |
| GET | `/hours-bank/adjustments` | Ajustes del periodo (`employee_id`, fechas) |
| POST | `/hours-bank/adjustments` | Ajuste manual (`attendance.manage`), minutos ≠ 0 y motivo |
| DELETE | `/hours-bank/adjustments/{id}` | Elimina un ajuste y audita el borrado |

El saldo es `trabajado − teórico + ajustes`. El teórico usa `employees.weekly_hours` (40 por
defecto, configurable al crear o modificar la ficha) prorrateado por los días del periodo dentro de
cada semana. Un saldo positivo son horas a favor del trabajador; uno negativo, pendientes de
compensar. Fechas invertidas devuelven 422 `invalid_range`; periodos de más de 93 días, 422
`range_too_long`; ajustes a más de un mes en el futuro o de más de un año atrás, 409
`invalid_effective_date`. Los fichajes no se modifican: los ajustes son la vía justificada.

## Prueba de entrega: GPS y firma

| Método | Ruta | Descripción |
|---|---|---|
| GET | `/deliveries/mine` | Repartos asignados al conductor (`deliveries.track`) |
| POST | `/deliveries/{id}/tracking` | Registra una posición GPS durante el tránsito |
| GET | `/deliveries/{id}/tracking` | Puntos, distancia Haversine y antigüedad de la última señal |
| GET | `/deliveries/{id}/tracking/latest` | Última posición o 404 |
| POST | `/deliveries/{id}/signature` | Firma multipart (`file` PNG, `signer_name`, `mark_delivered`) |
| GET | `/deliveries/{id}/signature` | Metadatos y verificación SHA-256 de la firma |
| GET | `/deliveries/{id}/signature/image` | Imagen PNG de la firma |

El nivel 4 solo puede operar sobre repartos cuyo `driver_employee_id` sea su ficha; niveles 1-3 y
auditoría consultan todos. Solo se admite GPS y firma en estado `in_transit` (409
`delivery_not_in_transit`). Los puntos GPS y las firmas son append-only: no hay endpoints de
edición ni borrado y los triggers de base de datos los protegen.

La distancia descarta segmentos con velocidad implícita superior a 55 m/s, saltos de más de 5 km
o precisión declarada peor de 500 m; el punto se conserva, pero no infla la distancia. La firma se
valida como PNG real (Pillow), entre 50×30 y 4000×4000 px y máximo 2 MB; se guarda con SHA-256 y
una segunda firma devuelve 409 `delivery_already_signed`. Si `mark_delivered=true`, el reparto pasa
a `delivered`, se sella la hora y los palés a `shipped` en la misma transacción. La descarga
incluye `X-Content-SHA256` y `Cache-Control: private, no-store`.

## Llamadas y telefonía

| Método | Ruta | Descripción |
|---|---|---|
| GET | `/calls/config` | Modo, dominio SIP, proveedor configurado y mensaje operativo |
| GET | `/calls` | Historial paginado (`status`, `search`) |
| GET | `/calls/{id}` | Detalle con enlaces `tel:`, `sip:` y `dial_uri` |
| POST | `/calls` | Registra la llamada y, en modo webhook, la envía al proveedor |
| PATCH | `/calls/{id}` | `in_progress`, `completed` o `failed` con resultado |
| POST | `/calls/callback` | Confirmación del proveedor (`X-Telephony-Token` o Bearer) |

Requiere `calls.manage` (niveles 1-3). El teléfono se normaliza a dígitos con prefijo `+`
opcional (7-15 dígitos; 422 `invalid_phone`). En modo `handoff` el servidor no llama: devuelve
`tel:` y, si `TELEPHONY_SIP_DOMAIN` está definido, `sip:` para que el softphone del dispositivo
abra la llamada. En modo `webhook` se envía `to`, `contact_name`, `purpose`, `reference` y
`extension` al proveedor; sin URL se devuelve 503 `telephony_not_configured`. Un fallo del
proveedor deja la llamada `failed`, auditada, y devuelve 502 `telephony_provider_error`. El
callback acepta `reference` (ID interno) o `provider_call_id`, actualiza el estado y es idempotente
si repite el mismo estado/resultado; una llamada ya cerrada con otro estado devuelve 409
`call_closed`. Sin `TELEPHONY_CALLBACK_TOKEN` responde 503; con token incorrecto, 401. No se
almacena audio ni se marca una llamada como completada sin confirmación o cierre humano.

## AURORA Voice

| Método | Ruta | Descripción |
|---|---|---|
| GET | `/voice/status` | STT del navegador, TTS configurado, voz, modelo, disponibilidad y salida de red |
| POST | `/voice/query` | `{text, locale}`: interpreta la transcripción y consulta datos reales |
| POST | `/voice/speak` | `{text, voice?, rate?}`: devuelve `audio/wav` o `audio/mpeg` según proveedor |

Intenciones: `product_location`, `product_not_found`, `low_stock`, `open_tasks`, `open_incidents`,
`pending_deliveries`, `summary`, `forbidden` y `unknown`. Cada respuesta incluye `answer` en español,
`data` estructurado, `suggestions` y `confidence`. El reconocimiento y la síntesis usan la Web
Speech API del navegador; el servidor no recibe audio ni guarda el historial. Los permisos se
comprueban por intención: un operario puede consultar stock pero no el resumen global de tareas.
El proveedor de intenciones es intercambiable con `VOICE_PROVIDER` (el incluido es
`aurora-builtin`, local y determinista).

`POST /voice/speak` requiere `inventory.read`, acepta hasta `VOICE_TTS_MAX_CHARS` caracteres y
devuelve las cabeceras `X-Voice-Provider`, `X-Voice-Name`, `X-Voice-Cached` y `X-Voice-Bytes`. Los
proveedores son:

| `VOICE_TTS_PROVIDER` | Formato | Red | Requisitos |
|---|---|---|---|
| `piper` (por defecto) | `audio/wav` | Ninguna | Modelo ONNX local (`VOICE_TTS_MODEL_PATH`) y `piper-tts` |
| `edge` | `audio/mpeg` | Salida a Microsoft | `edge-tts`; sin clave |
| `openai` | `audio/mpeg` | Salida a OpenAI | `VOICE_TTS_API_KEY` |
| `browser` | — | Ninguna | El servidor devuelve 409 `tts_browser_only` y el frontend usa `SpeechSynthesis` |

El audio se cachea por SHA-256 de proveedor, voz, velocidad y texto; no se guarda el texto en
nombres de archivo ni en logs. Errores: 422 `empty_text`/`text_too_long`, 409 `tts_browser_only`,
503 `tts_not_configured` y 502 `tts_provider_error`/`tts_empty_audio`. `VOICE_TTS_VOICE` debe
corresponder al proveedor (por ejemplo `es_ES-davefx-medium` para Piper o `es-ES-ElviraNeural` para
Edge). Con `piper`, el audio no sale del servidor y no se envía a terceros.
