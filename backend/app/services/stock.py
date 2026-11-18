"""Stock engine.

Invariants enforced here (and, where possible, by database constraints):

1. Stock only changes when a movement is confirmed, inside one transaction.
2. A deduction can never exceed the *available* quantity
   (``quantity - reserved_quantity``); quantities can never go negative.
3. Every affected stock level is recorded as an immutable allocation row, so
   the ledger explains exactly which pallet/location was touched.
4. Confirming the same movement twice is impossible (status transition guard),
   and duplicate requests are rejected through a unique idempotency key.
5. Unit-tracked products keep one record per physical item (AUR-OBJ-*).
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.enums import (
    INBOUND_TYPES,
    OUTBOUND_TYPES,
    MovementStatus,
    MovementType,
    PalletStatus,
    ReservationStatus,
    TrackingMode,
    UnitStatus,
    movement_direction,
)
from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.core.timeutils import utcnow
from app.models import (
    Employee,
    Location,
    MovementAllocation,
    MovementUnit,
    Pallet,
    Product,
    ProductBatch,
    ProductUnit,
    StockLevel,
    StockMovement,
    StockReservation,
    User,
)
from app.services.audit import record_audit
from app.services.sequences import next_code


def _d(value: Decimal | float | int | str) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.001"))


class StockEngine:
    def __init__(self, db: Session) -> None:
        self.db = db

    # -- helpers ---------------------------------------------------------
    def _location(self, location_id: str) -> Location:
        location = self.db.get(Location, location_id)
        if location is None:
            raise NotFoundError("Ubicación", location_id)
        if not location.is_active:
            raise ValidationError(f"La ubicación {location.full_code} está desactivada.")
        return location

    def _pallet(self, pallet_id: str | None) -> Pallet | None:
        if not pallet_id:
            return None
        pallet = self.db.get(Pallet, pallet_id)
        if pallet is None:
            raise NotFoundError("Palé", pallet_id)
        return pallet

    def _level(
        self,
        product_id: str,
        location_id: str,
        pallet_id: str | None,
        *,
        lock: bool = True,
        create: bool = False,
    ) -> StockLevel | None:
        stmt = select(StockLevel).where(
            StockLevel.product_id == product_id,
            StockLevel.location_id == location_id,
        )
        stmt = stmt.where(StockLevel.pallet_id == pallet_id) if pallet_id else stmt.where(
            StockLevel.pallet_id.is_(None)
        )
        if lock:
            stmt = stmt.with_for_update()
        level = self.db.scalars(stmt).first()
        if level is None and create:
            level = StockLevel(
                product_id=product_id,
                location_id=location_id,
                pallet_id=pallet_id,
                quantity=Decimal("0"),
                reserved_quantity=Decimal("0"),
            )
            self.db.add(level)
            try:
                self.db.flush()
            except IntegrityError:
                self.db.rollback()
                raise ConflictError(
                    "Conflicto de concurrencia al crear el nivel de stock. Reintente la operación."
                ) from None
        return level

    def expire_due_reservations(self) -> list[StockReservation]:
        """Release active reservations past their expiry date.

        Expiry is enforced by the server (not only shown in the UI): the reserved
        quantity returns to ``available`` before any stock is read or consumed.
        """
        now = utcnow()
        due = list(
            self.db.scalars(
                select(StockReservation)
                .where(
                    StockReservation.status == ReservationStatus.ACTIVE,
                    StockReservation.expires_at.isnot(None),
                    StockReservation.expires_at < now,
                )
                .with_for_update()
            ).all()
        )
        for reservation in due:
            self.release_reservation(reservation)
            reservation.status = ReservationStatus.EXPIRED
            reservation.released_at = now
        if due:
            self.db.flush()
        return due

    def _source_levels(
        self, product_id: str, location_id: str, pallet_id: str | None, quantity: Decimal
    ) -> list[StockLevel]:
        self.expire_due_reservations()
        stmt = select(StockLevel).where(
            StockLevel.product_id == product_id,
            StockLevel.location_id == location_id,
            StockLevel.quantity > 0,
        )
        if pallet_id:
            stmt = stmt.where(StockLevel.pallet_id == pallet_id)
        stmt = stmt.order_by(StockLevel.updated_at.asc()).with_for_update()
        levels = list(self.db.scalars(stmt).all())
        available = sum((lvl.quantity - lvl.reserved_quantity for lvl in levels), Decimal("0"))
        if available < quantity:
            where = "la ubicación indicada"
            if pallet_id:
                pallet = self._pallet(pallet_id)
                where = f"el palé {pallet.code if pallet else pallet_id}"
            raise ValidationError(
                f"Stock disponible insuficiente en {where}: disponible {available}, solicitado {quantity}.",
                code="insufficient_stock",
                details={"available": str(available), "requested": str(quantity)},
            )
        return levels

    def _allocate_out(
        self, movement: StockMovement, levels: list[StockLevel], quantity: Decimal
    ) -> None:
        remaining = quantity
        for level in levels:
            if remaining <= 0:
                break
            available = level.quantity - level.reserved_quantity
            take = min(available, remaining)
            if take <= 0:
                continue
            level.quantity -= take
            remaining -= take
            self.db.add(
                MovementAllocation(
                    movement_id=movement.id,
                    product_id=movement.product_id,
                    location_id=level.location_id,
                    pallet_id=level.pallet_id,
                    quantity=-take,
                )
            )
        if remaining != 0:
            raise ValidationError("No se pudo asignar el stock solicitado. Operación cancelada.")

    def _allocate_in(
        self, movement: StockMovement, level: StockLevel, quantity: Decimal
    ) -> None:
        level.quantity += quantity
        self.db.add(
            MovementAllocation(
                movement_id=movement.id,
                product_id=movement.product_id,
                location_id=level.location_id,
                pallet_id=level.pallet_id,
                quantity=quantity,
            )
        )

    # -- public API ------------------------------------------------------
    def available(self, product_id: str, location_id: str | None = None, pallet_id: str | None = None) -> Decimal:
        self.expire_due_reservations()
        stmt = select(StockLevel).where(StockLevel.product_id == product_id)
        if location_id:
            stmt = stmt.where(StockLevel.location_id == location_id)
        if pallet_id:
            stmt = stmt.where(StockLevel.pallet_id == pallet_id)
        levels = self.db.scalars(stmt).all()
        return sum((lvl.quantity - lvl.reserved_quantity for lvl in levels), Decimal("0"))

    def reserve(
        self,
        *,
        product_id: str,
        location_id: str,
        pallet_id: str | None,
        quantity: Decimal,
        reference: str,
        actor: User,
        expires_at: datetime | None = None,
    ) -> StockReservation:
        quantity = _d(quantity)
        if quantity <= 0:
            raise ValidationError("La cantidad a reservar debe ser mayor que cero.")
        product = self.db.get(Product, product_id)
        if product is None:
            raise NotFoundError("Producto", product_id)
        self._location(location_id)

        levels = self._source_levels(product_id, location_id, pallet_id, quantity)
        remaining = quantity
        for level in levels:
            if remaining <= 0:
                break
            available = level.quantity - level.reserved_quantity
            take = min(available, remaining)
            if take <= 0:
                continue
            level.reserved_quantity += take
            remaining -= take

        reservation = StockReservation(
            reference=reference,
            product_id=product_id,
            location_id=location_id,
            pallet_id=pallet_id,
            quantity=quantity,
            expires_at=expires_at,
            created_by=actor.id,
        )
        self.db.add(reservation)
        self.db.flush()
        return reservation

    def release_reservation(self, reservation: StockReservation, *, consume: bool = False) -> None:
        if reservation.status != ReservationStatus.ACTIVE:
            return
        stmt = (
            select(StockLevel)
            .where(
                StockLevel.product_id == reservation.product_id,
                StockLevel.location_id == reservation.location_id,
            )
            .with_for_update()
        )
        stmt = (
            stmt.where(StockLevel.pallet_id == reservation.pallet_id)
            if reservation.pallet_id
            else stmt.where(StockLevel.pallet_id.is_(None))
        )
        remaining = reservation.quantity
        levels = list(self.db.scalars(stmt).all())
        for level in levels:
            if remaining <= 0:
                break
            release = min(level.reserved_quantity, remaining)
            level.reserved_quantity -= release
            remaining -= release
        if remaining > 0:
            # Reservation spans several levels/pallets (or stock was rebuilt):
            # clamp any residue so the invariant reserved <= quantity holds.
            for level in levels:
                if remaining <= 0:
                    break
                release = min(level.reserved_quantity, remaining)
                level.reserved_quantity -= release
                remaining -= release
        reservation.status = ReservationStatus.CONSUMED if consume else ReservationStatus.RELEASED
        reservation.released_at = utcnow()

    # -- movement creation ----------------------------------------------
    def create_movement(
        self,
        *,
        actor: User,
        movement_type: MovementType,
        product_id: str,
        quantity: Decimal | float | str,
        from_location_id: str | None = None,
        to_location_id: str | None = None,
        from_pallet_id: str | None = None,
        to_pallet_id: str | None = None,
        worker_id: str | None = None,
        batch_code: str | None = None,
        reason: str = "",
        document_ref: str = "",
        invoice_id: str | None = None,
        invoice_line_id: str | None = None,
        idempotency_key: str | None = None,
        unit_serials: list[str] | None = None,
        unit_codes: list[str] | None = None,
        reservation_id: str | None = None,
        confirm: bool = True,
        physical_confirmed: bool = False,
        ip: str | None = None,
        user_agent: str | None = None,
    ) -> StockMovement:
        quantity = _d(quantity)

        if idempotency_key:
            existing = self.db.scalars(
                select(StockMovement).where(StockMovement.idempotency_key == idempotency_key)
            ).first()
            if existing is not None:
                if (
                    existing.movement_type != movement_type
                    or existing.product_id != product_id
                    or existing.quantity != quantity
                ):
                    raise ConflictError(
                        "La clave de idempotencia ya se usó con otra operación.",
                        code="idempotency_mismatch",
                    )
                return existing

        product = self.db.get(Product, product_id)
        if product is None:
            raise NotFoundError("Producto", product_id)
        if not product.is_active:
            raise ValidationError("El producto está desactivado.")

        direction = movement_direction(movement_type)
        if direction.value == "adjustment":
            if quantity == 0:
                raise ValidationError("El ajuste no puede tener cantidad cero.")
            if not reason:
                raise ValidationError("Los ajustes requieren un motivo documentado.")
            location_id = to_location_id or from_location_id
            if not location_id:
                raise ValidationError("El ajuste requiere una ubicación.")
            self._location(location_id)
            if quantity < 0:
                from_location_id, to_location_id = location_id, None
            else:
                from_location_id, to_location_id = None, location_id
        elif direction.value == "inbound":
            if not to_location_id:
                raise ValidationError("El movimiento de entrada requiere ubicación de destino.")
            self._location(to_location_id)
            from_location_id = None
            if quantity <= 0:
                raise ValidationError("La cantidad debe ser mayor que cero.")
            if product.tracking_mode == TrackingMode.BATCH and not batch_code:
                raise ValidationError("Este producto requiere lote (batch) en la recepción.")
        elif direction.value == "outbound":
            if not from_location_id:
                raise ValidationError("El movimiento de salida requiere ubicación de origen.")
            self._location(from_location_id)
            to_location_id = None
            to_pallet_id = None
            if quantity <= 0:
                raise ValidationError("La cantidad debe ser mayor que cero.")
        else:  # transfer
            if not from_location_id or not to_location_id:
                raise ValidationError("La transferencia requiere ubicación de origen y destino.")
            self._location(from_location_id)
            self._location(to_location_id)
            if quantity <= 0:
                raise ValidationError("La cantidad debe ser mayor que cero.")
            if from_location_id == to_location_id and from_pallet_id == to_pallet_id:
                raise ValidationError("El origen y el destino son idénticos.")
            if product.tracking_mode == TrackingMode.BATCH and not batch_code:
                raise ValidationError("Este producto requiere lote (batch) para moverse.")

        if worker_id:
            employee = self.db.get(Employee, worker_id)
            if employee is None:
                raise NotFoundError("Trabajador", worker_id)

        from_pallet = self._pallet(from_pallet_id)
        to_pallet = self._pallet(to_pallet_id)
        # A relocation moves the pallet itself, so the pallet's stored location
        # is still the origin while the movement is being written.
        relocating_pallet = movement_type == MovementType.RELOCATION
        if not relocating_pallet and from_pallet and from_location_id and from_pallet.location_id != from_location_id:
            raise ValidationError(f"El palé {from_pallet.code} no está en la ubicación de origen indicada.")
        if not relocating_pallet and to_pallet and to_location_id and to_pallet.location_id != to_location_id:
            raise ValidationError(f"El palé {to_pallet.code} no está en la ubicación de destino indicada.")
        if to_pallet and to_pallet.status == PalletStatus.SHIPPED:
            raise ValidationError("No se puede estocar mercancía en un palé ya expedido.")

        movement = StockMovement(
            reference=next_code(self.db, "movement"),
            movement_type=movement_type,
            status=MovementStatus.DRAFT,
            product_id=product_id,
            quantity=quantity,
            from_location_id=from_location_id,
            to_location_id=to_location_id,
            from_pallet_id=from_pallet_id,
            to_pallet_id=to_pallet_id,
            worker_id=worker_id,
            batch_code=batch_code,
            reason=reason,
            document_ref=document_ref,
            invoice_id=invoice_id,
            invoice_line_id=invoice_line_id,
            idempotency_key=idempotency_key,
            physical_confirmed=False,
            created_by=actor.id,
        )
        self.db.add(movement)
        self.db.flush()

        if unit_serials or unit_codes:
            self._attach_units(movement, product, unit_serials or unit_codes or [])

        if confirm:
            self.confirm(movement, actor=actor, physical_confirmed=physical_confirmed, ip=ip, user_agent=user_agent,
                         reservation_id=reservation_id)
        else:
            record_audit(
                self.db,
                actor_user_id=actor.id,
                actor_label=actor.full_name,
                action="movement.created",
                entity_type="stock_movement",
                entity_id=movement.id,
                after=self._snapshot(movement),
                ip=ip,
                user_agent=user_agent,
            )
        return movement

    def _attach_units(self, movement: StockMovement, product: Product, identifiers: list[str]) -> None:
        if product.tracking_mode != TrackingMode.UNIT:
            raise ValidationError("Solo los productos con seguimiento unitario admiten códigos de unidad.")
        identifiers = [i.strip() for i in identifiers if i and i.strip()]
        if len(identifiers) != int(movement.quantity):
            raise ValidationError(
                "El número de unidades debe coincidir con la cantidad del movimiento.",
                details={"provided": len(identifiers), "quantity": str(movement.quantity)},
            )
        if movement_direction(movement.movement_type).value != "inbound":
            raise ValidationError("Los códigos de unidad solo se indican en entradas.")
        seen: set[str] = set()
        for serial in identifiers:
            if serial in seen:
                raise ValidationError(f"Unidad duplicada en la operación: {serial}")
            seen.add(serial)
            unit = ProductUnit(
                code=next_code(self.db, "unit"),
                product_id=product.id,
                serial_number=serial,
                batch_code=movement.batch_code,
                location_id=movement.to_location_id,
                pallet_id=movement.to_pallet_id,
                invoice_id=movement.invoice_id,
            )
            self.db.add(unit)
            self.db.flush()
            self.db.add(MovementUnit(movement_id=movement.id, unit_id=unit.id))

    def _snapshot(self, movement: StockMovement) -> dict:
        return {
            "reference": movement.reference,
            "movement_type": movement.movement_type,
            "status": movement.status,
            "product_id": movement.product_id,
            "quantity": movement.quantity,
            "from_location_id": movement.from_location_id,
            "to_location_id": movement.to_location_id,
            "from_pallet_id": movement.from_pallet_id,
            "to_pallet_id": movement.to_pallet_id,
            "batch_code": movement.batch_code,
            "reason": movement.reason,
            "document_ref": movement.document_ref,
            "worker_id": movement.worker_id,
        }

    def confirm(
        self,
        movement: StockMovement,
        *,
        actor: User,
        physical_confirmed: bool = False,
        ip: str | None = None,
        user_agent: str | None = None,
        reservation_id: str | None = None,
    ) -> StockMovement:
        if movement.status == MovementStatus.CONFIRMED:
            raise ConflictError(
                "El movimiento ya está confirmado.", code="already_confirmed"
            )
        if movement.status == MovementStatus.CANCELLED:
            raise ConflictError("No se puede confirmar un movimiento cancelado.", code="movement_cancelled")

        product = self.db.get(Product, movement.product_id)
        if product is None:
            raise NotFoundError("Producto", movement.product_id)

        quantity = _d(movement.quantity)
        direction = movement_direction(movement.movement_type).value

        if reservation_id:
            reservation = self.db.get(StockReservation, reservation_id)
            if reservation is None:
                raise NotFoundError("Reserva", reservation_id)
            if reservation.product_id != movement.product_id:
                raise ValidationError("La reserva no corresponde al producto del movimiento.")
            if direction not in {"outbound"}:
                raise ValidationError("Solo las salidas pueden consumir una reserva.")
            self.release_reservation(reservation, consume=True)

        if direction == "inbound":
            level = self._level(
                movement.product_id, movement.to_location_id, movement.to_pallet_id, create=True
            )
            assert level is not None
            self._allocate_in(movement, level, quantity)
            self._apply_batch_in(movement, product, quantity)
            self._apply_units_in(movement, product, quantity)
        elif direction == "outbound":
            levels = self._source_levels(
                movement.product_id, movement.from_location_id, movement.from_pallet_id, quantity
            )
            self._allocate_out(movement, levels, quantity)
            self._apply_batch_out(movement, product, quantity)
            self._apply_units_out(movement, product, quantity)
        elif direction == "transfer":
            levels = self._source_levels(
                movement.product_id, movement.from_location_id, movement.from_pallet_id, quantity
            )
            self._allocate_out(movement, levels, quantity)
            target = self._level(
                movement.product_id, movement.to_location_id, movement.to_pallet_id, create=True
            )
            assert target is not None
            self._allocate_in(movement, target, quantity)
            self._apply_batch_move(movement, product, quantity)
            self._apply_units_move(movement)
        else:  # adjustment
            if quantity > 0:
                level = self._level(
                    movement.product_id, movement.to_location_id, movement.to_pallet_id, create=True
                )
                assert level is not None
                self._allocate_in(movement, level, quantity)
            else:
                levels = self._source_levels(
                    movement.product_id, movement.from_location_id, movement.from_pallet_id, -quantity
                )
                self._allocate_out(movement, levels, -quantity)

        movement.status = MovementStatus.CONFIRMED
        movement.confirmed_at = utcnow()
        movement.confirmed_by = actor.id
        movement.physical_confirmed = physical_confirmed
        movement.physical_confirmed_at = utcnow() if physical_confirmed else None
        self.db.flush()

        if movement.invoice_line_id:
            self._register_invoice_receipt(movement)

        record_audit(
            self.db,
            actor_user_id=actor.id,
            actor_label=actor.full_name,
            action="movement.confirmed",
            entity_type="stock_movement",
            entity_id=movement.id,
            before={"status": MovementStatus.DRAFT.value},
            after=self._snapshot(movement),
            ip=ip,
            user_agent=user_agent,
        )
        return movement

    def cancel(self, movement: StockMovement, *, actor: User, reason: str, ip: str | None = None) -> StockMovement:
        if movement.status != MovementStatus.DRAFT:
            raise ConflictError("Solo pueden cancelarse movimientos en borrador.")
        if not reason:
            raise ValidationError("Indique el motivo de la cancelación.")
        movement.status = MovementStatus.CANCELLED
        movement.cancelled_at = utcnow()
        movement.cancelled_by = actor.id
        movement.cancellation_reason = reason
        self.db.flush()
        record_audit(
            self.db,
            actor_user_id=actor.id,
            actor_label=actor.full_name,
            action="movement.cancelled",
            entity_type="stock_movement",
            entity_id=movement.id,
            after={"status": "cancelled", "reason": reason},
            ip=ip,
        )
        return movement

    # -- side effects ----------------------------------------------------
    def _apply_batch_in(self, movement: StockMovement, product: Product, quantity: Decimal) -> None:
        if product.tracking_mode != TrackingMode.BATCH or not movement.batch_code:
            return
        batch = self.db.scalars(
            select(ProductBatch)
            .where(
                ProductBatch.product_id == product.id,
                ProductBatch.batch_code == movement.batch_code,
            )
            .with_for_update()
        ).first()
        if batch is None:
            batch = ProductBatch(
                product_id=product.id,
                batch_code=movement.batch_code,
                quantity_received=quantity,
                quantity_remaining=quantity,
                invoice_id=movement.invoice_id,
            )
            self.db.add(batch)
        else:
            batch.quantity_received += quantity
            batch.quantity_remaining += quantity
        self.db.flush()

    def _apply_batch_out(self, movement: StockMovement, product: Product, quantity: Decimal) -> None:
        if product.tracking_mode != TrackingMode.BATCH or not movement.batch_code:
            return
        batch = self.db.scalars(
            select(ProductBatch)
            .where(
                ProductBatch.product_id == product.id,
                ProductBatch.batch_code == movement.batch_code,
            )
            .with_for_update()
        ).first()
        if batch is None or batch.quantity_remaining < quantity:
            raise ValidationError(
                f"Lote {movement.batch_code} sin existencias suficientes.",
                code="insufficient_batch",
            )
        batch.quantity_remaining -= quantity

    def _apply_batch_move(self, movement: StockMovement, product: Product, quantity: Decimal) -> None:
        # Batches are location-agnostic: moving stock does not change lot balances.
        _ = (movement, product, quantity)

    def _apply_units_in(self, movement: StockMovement, product: Product, quantity: Decimal) -> None:
        if product.tracking_mode != TrackingMode.UNIT:
            return
        linked = len(movement.units)
        if linked == 0:
            for _ in range(int(quantity)):
                unit = ProductUnit(
                    code=next_code(self.db, "unit"),
                    product_id=product.id,
                    location_id=movement.to_location_id,
                    pallet_id=movement.to_pallet_id,
                    batch_code=movement.batch_code,
                    invoice_id=movement.invoice_id,
                    status=UnitStatus.IN_STOCK,
                )
                self.db.add(unit)
                self.db.flush()
                self.db.add(MovementUnit(movement_id=movement.id, unit_id=unit.id))
        elif linked != int(quantity):
            raise ValidationError("Las unidades asociadas no coinciden con la cantidad.")
        for link in movement.units:
            link.unit.location_id = movement.to_location_id
            link.unit.pallet_id = movement.to_pallet_id
            link.unit.status = UnitStatus.IN_STOCK

    def _apply_units_out(self, movement: StockMovement, product: Product, quantity: Decimal) -> None:
        if product.tracking_mode != TrackingMode.UNIT:
            return
        if movement.units:
            for link in movement.units:
                unit = link.unit
                if unit.status != UnitStatus.IN_STOCK:
                    raise ValidationError(f"La unidad {unit.code} no está disponible para salida.")
                unit.status = UnitStatus.SHIPPED
                unit.location_id = None
                unit.pallet_id = None
            return
        stmt = select(ProductUnit).where(
            ProductUnit.product_id == product.id,
            ProductUnit.location_id == movement.from_location_id,
            ProductUnit.status == UnitStatus.IN_STOCK,
        )
        if movement.from_pallet_id:
            stmt = stmt.where(ProductUnit.pallet_id == movement.from_pallet_id)
        stmt = stmt.order_by(ProductUnit.created_at.asc()).limit(int(quantity)).with_for_update()
        units = list(self.db.scalars(stmt).all())
        if len(units) < int(quantity):
            raise ValidationError(
                "No hay unidades individuales suficientes en la ubicación de origen.",
                code="insufficient_units",
                details={"available": len(units), "requested": str(quantity)},
            )
        for unit in units:
            unit.status = UnitStatus.SHIPPED
            unit.location_id = None
            unit.pallet_id = None
            self.db.add(MovementUnit(movement_id=movement.id, unit_id=unit.id))

    def _apply_units_move(self, movement: StockMovement) -> None:
        if not movement.units:
            return
        for link in movement.units:
            link.unit.location_id = movement.to_location_id
            link.unit.pallet_id = movement.to_pallet_id

    def _register_invoice_receipt(self, movement: StockMovement) -> None:
        from app.models import InvoiceLine  # local import avoids a cycle

        line = self.db.get(InvoiceLine, movement.invoice_line_id, with_for_update=True)
        if line is None:
            return
        if movement.movement_type not in INBOUND_TYPES:
            return
        line.received_quantity = (line.received_quantity or Decimal("0")) + movement.quantity
        if line.received_quantity > line.quantity:
            line.review_required = True
        self.db.flush()

    # -- pallet helpers --------------------------------------------------
    def seal_pallet(self, pallet: Pallet, *, actor: User) -> Pallet:
        if pallet.status != PalletStatus.OPEN:
            raise ConflictError("Solo puede precintarse un palé abierto.")
        if not pallet.items:
            raise ValidationError("No se puede precintar un palé vacío.")
        pallet.status = PalletStatus.SEALED
        pallet.sealed_at = utcnow()
        self.db.flush()
        record_audit(
            self.db,
            actor_user_id=actor.id,
            actor_label=actor.full_name,
            action="pallet.sealed",
            entity_type="pallet",
            entity_id=pallet.id,
            after={"code": pallet.code, "status": pallet.status.value},
        )
        return pallet

    def move_pallet(
        self,
        pallet: Pallet,
        *,
        actor: User,
        destination_location_id: str,
        worker_id: str | None = None,
        reason: str = "Reubicación de palé",
        ip: str | None = None,
    ) -> list[StockMovement]:
        if pallet.status not in {PalletStatus.SEALED, PalletStatus.OPEN}:
            raise ConflictError("Solo puede moverse un palé almacenado o abierto.")
        destination = self._location(destination_location_id)
        if destination.warehouse_id != pallet.warehouse_id:
            raise ValidationError("El palé no puede moverse a otro almacén sin una operación de traslado.")
        if pallet.location_id == destination_location_id:
            raise ValidationError("El palé ya se encuentra en esa ubicación.")
        occupied = self.db.scalars(
            select(Pallet).where(
                Pallet.location_id == destination_location_id,
                Pallet.id != pallet.id,
                Pallet.status.in_([PalletStatus.SEALED, PalletStatus.OPEN]),
            )
        ).all()
        if len(occupied) >= destination.capacity_pallets:
            raise ConflictError(
                f"La ubicación {destination.full_code} está ocupada (capacidad {destination.capacity_pallets})."
            )

        movements: list[StockMovement] = []
        for item in pallet.items:
            movements.append(
                self.create_movement(
                    actor=actor,
                    movement_type=MovementType.RELOCATION,
                    product_id=item.product_id,
                    quantity=item.quantity,
                    from_location_id=pallet.location_id,
                    to_location_id=destination_location_id,
                    from_pallet_id=pallet.id,
                    to_pallet_id=pallet.id,
                    worker_id=worker_id,
                    reason=reason,
                    confirm=True,
                    ip=ip,
                )
            )
        pallet.location_id = destination_location_id
        self.db.flush()
        record_audit(
            self.db,
            actor_user_id=actor.id,
            actor_label=actor.full_name,
            action="pallet.moved",
            entity_type="pallet",
            entity_id=pallet.id,
            after={"code": pallet.code, "location": destination.full_code, "movements": len(movements)},
            ip=ip,
        )
        return movements

    def ship_pallet(
        self,
        pallet: Pallet,
        *,
        actor: User,
        worker_id: str | None = None,
        document_ref: str = "",
        reason: str = "Expedición de palé",
        ip: str | None = None,
    ) -> list[StockMovement]:
        if pallet.status not in {PalletStatus.SEALED, PalletStatus.OPEN}:
            raise ConflictError("El palé no está disponible para expedición.")
        if not pallet.items:
            raise ValidationError("El palé no contiene mercancía.")
        movements: list[StockMovement] = []
        for item in pallet.items:
            movements.append(
                self.create_movement(
                    actor=actor,
                    movement_type=MovementType.SHIPMENT,
                    product_id=item.product_id,
                    quantity=item.quantity,
                    from_location_id=pallet.location_id,
                    from_pallet_id=pallet.id,
                    worker_id=worker_id,
                    reason=reason,
                    document_ref=document_ref,
                    confirm=True,
                    ip=ip,
                )
            )
        pallet.status = PalletStatus.SHIPPED
        self.db.flush()
        record_audit(
            self.db,
            actor_user_id=actor.id,
            actor_label=actor.full_name,
            action="pallet.shipped",
            entity_type="pallet",
            entity_id=pallet.id,
            after={"code": pallet.code, "movements": len(movements), "document_ref": document_ref},
            ip=ip,
        )
        return movements
