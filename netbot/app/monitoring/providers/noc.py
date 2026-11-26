"""Telemetría del NOC mediante consultas acotadas de PostgreSQL."""
import asyncio
from collections import defaultdict
from math import isfinite

from psycopg import AsyncConnection, Error
from pydantic import SecretStr

from ..schemas import (
    CollectionIssue, FirewallStatistics, InterfaceTrafficHistory, IssueKind,
    StateTableStats, TrafficRatePoint,
)
from .base import CollectionResult


_HISTORY_LIMIT = 50_000
_TRAFFIC = """
SELECT interfaz, ts, entrada_mbps, salida_mbps, ts >= now() - interval '60 seconds'
FROM v2.interfaz_tasa_15s
WHERE ts >= now() - make_interval(secs => %s) AND ts <= now() + interval '5 seconds'
  AND entrada_mbps >= 0 AND salida_mbps >= 0
ORDER BY ts DESC, interfaz
LIMIT %s
"""
_STATES = """
SELECT ts, estados_pf FROM v2.core_1m
WHERE ts >= now() - interval '3 minutes' AND ts <= now() + interval '5 seconds'
  AND estados_pf >= 0
ORDER BY ts DESC LIMIT 1
"""
_BLOCKS = """
SELECT max(minuto), sum(paquetes) FROM v2.bloqueo_1m
WHERE minuto >= date_trunc('minute', now()) - interval '5 minutes'
  AND minuto < date_trunc('minute', now()) AND paquetes >= 0
"""


def _missing(component):
    return CollectionIssue(component=component, kind=IssueKind.INVALID_RESPONSE,
                           message="El NOC no devolvió mediciones recientes para este recurso.")


class NocTelemetry:
    def __init__(self, dsn: SecretStr, ca_bundle: str | None = None) -> None:
        self._dsn = dsn
        self._tls = {"sslmode": "verify-full", "sslrootcert": ca_bundle} if ca_bundle else {"sslmode": "require"}

    async def _query(self, component, query, params=()):
        try:
            async with asyncio.timeout(8):
                async with await AsyncConnection.connect(
                    self._dsn.get_secret_value(), **self._tls, connect_timeout=5,
                    channel_binding="require", require_auth="scram-sha-256", gssencmode="disable",
                    application_name="netbot_noc_monitoring",
                ) as connection:
                    await connection.execute("SET TRANSACTION READ ONLY")
                    await connection.execute("SET LOCAL statement_timeout = '3s'")
                    await connection.execute("SET LOCAL lock_timeout = '1s'")
                    cursor = await connection.execute(query, params)
                    return await cursor.fetchall(), None
        except (TimeoutError, Error) as error:
            code = getattr(error, "sqlstate", None)
            kind = IssueKind.CONNECTION
            message = "No se pudo consultar el NOC."
            if isinstance(error, TimeoutError) or code == "57014":
                kind, message = IssueKind.TIMEOUT, "Se agotó el tiempo de consulta del NOC."
            elif code == "42501":
                kind, message = IssueKind.PERMISSION, "La cuenta del NOC no puede leer este recurso."
            return [], CollectionIssue(component=component, kind=kind, message=message)

    async def traffic(self, window_seconds: int) -> CollectionResult[list[InterfaceTrafficHistory]]:
        component = "noc.traffic"
        rows, issue = await self._query(component, _TRAFFIC, (window_seconds, _HISTORY_LIMIT + 1))
        if issue:
            return CollectionResult(None, [issue])
        if len(rows) > _HISTORY_LIMIT:
            return CollectionResult(None, [CollectionIssue(
                component=component, kind=IssueKind.INVALID_RESPONSE,
                message="La lectura del NOC supera el límite de muestras.",
            )])
        points = defaultdict(dict)
        latest = None
        for name, timestamp, inbound, outbound, fresh in rows:
            if not isfinite(inbound) or not isfinite(outbound):
                continue
            interface = name.decode("utf-8", errors="replace") if isinstance(name, bytes) else name
            if not interface:
                continue
            points[interface].setdefault(timestamp, TrafficRatePoint(
                timestamp=timestamp, bytes_in_per_second=float(inbound) * 125_000,
                bytes_out_per_second=float(outbound) * 125_000,
            ))
            if fresh and latest is None:
                latest = timestamp
        if latest is None:
            return CollectionResult(None, [_missing(component)])
        return CollectionResult([
            InterfaceTrafficHistory(interface_id=interface, points=[values[t] for t in sorted(values)])
            for interface, values in sorted(points.items())
        ], observed_at=latest)

    async def firewall(self) -> CollectionResult[FirewallStatistics]:
        (states, states_issue), (blocks, blocks_issue) = await asyncio.gather(
            self._query("noc.firewall.states", _STATES),
            self._query("noc.firewall.blocks", _BLOCKS),
        )
        state_at, count = states[0] if states else (None, None)
        block_at, blocked = blocks[0] if blocks else (None, None)
        issues = []
        if count is None:
            issues.append(states_issue or _missing("noc.firewall.states"))
        if blocked is None:
            issues.append(blocks_issue or _missing("noc.firewall.blocks"))
        timestamps = [stamp for stamp in (state_at, block_at) if stamp is not None]
        if not timestamps:
            return CollectionResult(None, issues)
        return CollectionResult(FirewallStatistics(
            states=StateTableStats(current_entries=count) if count is not None else None,
            logged_blocked_packets_5m=blocked,
        ), issues, observed_at=max(timestamps))
