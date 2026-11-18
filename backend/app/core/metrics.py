"""Métricas Prometheus en texto de exposición (sin dependencias externas).

El registro vive en memoria del proceso: contadores de peticiones por método,
ruta y estado, histograma de latencias y peticiones en vuelo. La ruta ``/metrics``
añade gauges de infraestructura y de negocio calculados en cada scrape.
"""

from __future__ import annotations

import math
import threading
import time
from collections import defaultdict
from typing import Iterable

#: Cubos del histograma en segundos (incluye +Inf al representar).
BUCKETS: tuple[float, ...] = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)

_lock = threading.Lock()
_requests: dict[tuple[str, str, int], int] = defaultdict(int)
_durations: dict[tuple[str, str], list] = {}
_in_flight = 0
PROCESS_START = time.time()

LabelSet = dict[str, str]
Sample = tuple[LabelSet, float]


def observe_request(method: str, route: str, status: int, seconds: float) -> None:
    """Registra una petición HTTP terminada."""
    global _in_flight
    key = (method.upper(), route, int(status))
    histogram = _durations.get((key[0], key[1]))
    with _lock:
        _requests[key] += 1
        if histogram is None:
            histogram = [0] * (len(BUCKETS) + 1)
            histogram.append(0.0)  # sum
            histogram.append(0)  # count
            _durations[(key[0], key[1])] = histogram
        for index, bound in enumerate(BUCKETS):
            if seconds <= bound:
                histogram[index] += 1
        histogram[len(BUCKETS)] += 1  # +Inf
        histogram[len(BUCKETS) + 1] += seconds
        histogram[len(BUCKETS) + 2] += 1


def request_started() -> None:
    global _in_flight
    with _lock:
        _in_flight += 1


def request_finished() -> None:
    global _in_flight
    with _lock:
        _in_flight = max(0, _in_flight - 1)


def in_flight() -> int:
    with _lock:
        return _in_flight


def reset() -> None:
    """Solo para pruebas: vacía el registro."""
    global _in_flight
    with _lock:
        _requests.clear()
        _durations.clear()
        _in_flight = 0


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def _labels(labels: LabelSet) -> str:
    if not labels:
        return ""
    rendered = ",".join(f'{key}="{_escape(str(value))}"' for key, value in sorted(labels.items()))
    return f"{{{rendered}}}"


def _number(value: float) -> str:
    if isinstance(value, int) or (isinstance(value, float) and value.is_integer()):
        return str(int(value))
    if math.isinf(value):
        return "+Inf" if value > 0 else "-Inf"
    return f"{value:.6f}".rstrip("0").rstrip(".")


def _metric(name: str, help_text: str, kind: str, samples: Iterable[Sample]) -> list[str]:
    lines = [f"# HELP {name} {help_text}", f"# TYPE {name} {kind}"]
    lines.extend(f"{name}{_labels(labels)} {_number(value)}" for labels, value in samples)
    return lines


def render(extra_gauges: Iterable[tuple[str, str, list[Sample]]] = ()) -> str:
    """Devuelve el texto de exposición Prometheus 0.0.4."""
    with _lock:
        requests = dict(_requests)
        durations = {key: list(value) for key, value in _durations.items()}
        current_in_flight = _in_flight

    lines: list[str] = []

    lines += _metric(
        "aurora_http_requests_total",
        "Peticiones HTTP atendidas, por método, ruta y estado.",
        "counter",
        [({"method": method, "route": route, "status": status}, count)
         for (method, route, status), count in sorted(requests.items())],
    )

    histogram_samples: list[Sample] = []
    for (method, route), values in sorted(durations.items()):
        # ``observe_request`` ya guarda cada cubo acumulado (le <= bound).
        for index, bound in enumerate(BUCKETS):
            histogram_samples.append(
                ({"method": method, "route": route, "le": _number(bound)}, values[index])
            )
        histogram_samples.append(
            ({"method": method, "route": route, "le": "+Inf"}, values[len(BUCKETS)])
        )
    # El histograma necesita sus _bucket/_sum/_count, no una única línea base.
    if histogram_samples:
        lines.append("# HELP aurora_http_request_duration_seconds Latencia de las peticiones HTTP en segundos.")
        lines.append("# TYPE aurora_http_request_duration_seconds histogram")
        for labels, value in histogram_samples:
            lines.append(f"aurora_http_request_duration_seconds_bucket{_labels(labels)} {_number(value)}")
        for (method, route), values in sorted(durations.items()):
            labels = {"method": method, "route": route}
            lines.append(
                f"aurora_http_request_duration_seconds_sum{_labels(labels)} "
                f"{_number(values[-2])}"
            )
            lines.append(
                f"aurora_http_request_duration_seconds_count{_labels(labels)} "
                f"{_number(values[-1])}"
            )

    lines += _metric(
        "aurora_http_requests_in_flight",
        "Peticiones HTTP en curso en este momento.",
        "gauge",
        [({}, current_in_flight)],
    )
    lines += _metric(
        "aurora_process_start_time_seconds",
        "Momento de arranque del proceso en segundos epoch.",
        "gauge",
        [({}, PROCESS_START)],
    )

    for name, help_text, samples in extra_gauges:
        lines += _metric(name, help_text, "gauge", samples)
    return "\n".join(lines) + "\n"
