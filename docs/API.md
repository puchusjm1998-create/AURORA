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
| GET | `/reservations` | Reservas activas por producto |
| POST | `/reservations` | Reservar cantidad disponible |
| POST | `/reservations/{id}/release` | Liberar reserva |

La reserva descuenta de `available` pero no mueve mercancía física. El stock reservado se muestra
en la ficha del producto y en las posiciones.

## Facturas y conciliación

| Método | Ruta | Descripción |
|---|---|---|
| GET/POST | `/invoices` | Listar / subir (multipart: `number`, `invoice_date`, `supplier_id`, `notes`, `file`) |
| GET/PATCH | `/invoices/{id}` | Consultar / cabecera |
| GET | `/invoices/{id}/file` | Descargar original (autenticado) |
| POST | `/invoices/{id}/lines` | Añadir línea (producto opcional) |
| DELETE | `/invoices/{id}/lines/{line_id}` | Eliminar línea sin recepciones |
| POST | `/invoices/{id}/reconcile` | Conciliar cantidades facturadas vs recibidas |
| GET | `/invoices/{id}/ocr-status` | Estado del OCR (`not_configured` sin proveedor) |

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
| GET | `/dashboard` | KPIs, ocupación, top productos, stock bajo y actividad reciente |
| GET | `/audit` | Auditoría filtrable (`action`, `entity_type`, `actor`, fechas) |
| GET | `/reports/summary` | Valoración por categoría (coste, venta, margen) |
| GET | `/reports/inventory.csv` | Inventario detallado (UTF-8 con BOM, separador `;`) |
| GET | `/reports/movements.csv` | Libro de movimientos (`date_from`, `date_to`) |

La auditoría es append-only: triggers de base de datos rechazan `UPDATE` y `DELETE` sobre
`audit_logs`, y también la eliminación de movimientos de stock.

## Sistema

| Método | Ruta | Descripción |
|---|---|---|
| GET | `/system/info` | Versión, entorno, zona horaria, fase, implementado y pendiente |
| GET | `/system/health` | Comprobación de base de datos y almacenamiento |

`/healthz` (fuera de `/api`) es el endpoint ligero para balanceadores y contenedores.
