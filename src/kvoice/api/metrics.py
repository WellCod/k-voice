from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

streams_started = Counter(
    "kvoice_streams_started_total",
    "WebSocket streams iniciados",
)
streams_done = Counter(
    "kvoice_streams_done_total",
    "WebSocket streams concluídos normalmente",
)
streams_cancelled = Counter(
    "kvoice_streams_cancelled_total",
    "WebSocket streams cancelados pelo cliente",
)
streams_errors = Counter(
    "kvoice_streams_errors_total",
    "Erros em WebSocket streams",
    ["code"],
)
streams_active = Gauge(
    "kvoice_streams_active",
    "Streams WebSocket ativos no momento",
)
ttfa_seconds = Histogram(
    "kvoice_ttfa_seconds",
    "Tempo até o primeiro chunk de áudio (segundos)",
    buckets=[0.05, 0.1, 0.15, 0.2, 0.3, 0.5, 0.75, 1.0, 2.0],
)
