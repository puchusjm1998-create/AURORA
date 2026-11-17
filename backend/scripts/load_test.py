"""Prueba de carga HTTP contra una instancia de AURORA LOGISTICS AI.

Abre varias sesiones autenticadas y reparte peticiones de lectura durante la
duración indicada, midiendo latencias y errores reales. Solo usa ``httpx`` (ya
presente en el proyecto) y no crea ni modifica datos.

    cd backend
    ../.venv/bin/python -m scripts.load_test --base-url http://127.0.0.1:8000 \
        --concurrency 8 --duration 20 --email admin@aurora.demo --password 'Aurora2026!'

Salida: peticiones, errores, RPS y percentiles p50/p95/p99 en milisegundos.
Código de salida 1 si la tasa de error supera ``--max-error-rate``.
"""

from __future__ import annotations

import argparse
import asyncio
import math
import statistics
import sys
import time

import httpx

READ_PATHS = [
    "/api/v1/dashboard",
    "/api/v1/products?limit=20",
    "/api/v1/locations?limit=20",
    "/api/v1/pallets?limit=20",
    "/api/v1/tasks?limit=20",
    "/api/v1/incidents?limit=20",
    "/api/v1/deliveries?limit=20",
    "/api/v1/optimization/slotting?limit=5",
]


def percentile(values: list[float], fraction: float) -> float:
    """Percentil por interpolación lineal (0 <= fraction <= 1)."""
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = max(0.0, min(1.0, fraction)) * (len(ordered) - 1)
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[int(position)]
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


async def login(client: httpx.AsyncClient, email: str, password: str) -> None:
    response = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    response.raise_for_status()


async def worker(
    client: httpx.AsyncClient,
    paths: list[str],
    deadline: float,
    latencies: list[float],
    errors: list[int],
    counters: dict[str, int],
) -> None:
    index = counts = 0
    while time.perf_counter() < deadline:
        path = paths[index % len(paths)]
        started = time.perf_counter()
        try:
            response = await client.get(path)
            elapsed = (time.perf_counter() - started) * 1000
            latencies.append(elapsed)
            counters["requests"] += 1
            if response.status_code >= 400:
                errors.append(response.status_code)
        except httpx.HTTPError:
            counters["requests"] += 1
            errors.append(0)
        index += 1
        counts += 1


async def run(
    base_url: str,
    *,
    concurrency: int,
    duration: float,
    email: str,
    password: str,
    timeout: float,
    paths: list[str] | None = None,
) -> dict[str, float | int]:
    paths = paths or READ_PATHS
    latencies: list[float] = []
    errors: list[int] = []
    counters = {"requests": 0}
    deadline = time.perf_counter() + duration
    limits = httpx.Limits(max_connections=concurrency * 2, max_keepalive_connections=concurrency)
    async with httpx.AsyncClient(
        base_url=base_url.rstrip("/"), timeout=timeout, limits=limits
    ) as client:
        await login(client, email, password)
        started = time.perf_counter()
        await asyncio.gather(
            *(worker(client, paths, deadline, latencies, errors, counters) for _ in range(concurrency))
        )
        elapsed = time.perf_counter() - started
    total = counters["requests"]
    return {
        "requests": total,
        "errors": len(errors),
        "error_rate": (len(errors) / total) if total else 0.0,
        "rps": total / elapsed if elapsed else 0.0,
        "duration": elapsed,
        "p50": percentile(latencies, 0.50),
        "p95": percentile(latencies, 0.95),
        "p99": percentile(latencies, 0.99),
        "mean": statistics.fmean(latencies) if latencies else 0.0,
        "max": max(latencies) if latencies else 0.0,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prueba de carga de AURORA")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--email", default="admin@aurora.demo")
    parser.add_argument("--password", default="Aurora2026!")
    parser.add_argument("--concurrency", type=int, default=8)
    parser.add_argument("--duration", type=float, default=15.0, help="Segundos de carga")
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--max-error-rate", type=float, default=0.01)
    args = parser.parse_args(argv)

    if args.concurrency < 1 or args.duration <= 0:
        parser.error("--concurrency y --duration deben ser positivos")

    print(
        f"Carga: {args.concurrency} usuarios concurrentes durante {args.duration:.0f}s "
        f"contra {args.base_url}"
    )
    try:
        result = asyncio.run(
            run(
                args.base_url,
                concurrency=args.concurrency,
                duration=args.duration,
                email=args.email,
                password=args.password,
                timeout=args.timeout,
            )
        )
    except httpx.HTTPError as exc:
        print(f"No se pudo iniciar la prueba: {exc}", file=sys.stderr)
        return 2

    print(
        f"Peticiones: {result['requests']} | errores: {result['errors']} "
        f"({result['error_rate'] * 100:.2f} %) | {result['rps']:.1f} req/s"
    )
    print(
        f"Latencia ms: p50 {result['p50']:.0f} | p95 {result['p95']:.0f} | "
        f"p99 {result['p99']:.0f} | media {result['mean']:.0f} | máx {result['max']:.0f}"
    )
    if result["requests"] == 0:
        print("Sin peticiones completadas", file=sys.stderr)
        return 2
    return 1 if result["error_rate"] > args.max_error_rate else 0


if __name__ == "__main__":
    sys.exit(main())
