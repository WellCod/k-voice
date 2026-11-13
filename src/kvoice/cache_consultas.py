"""Cache em memória, com validade curta, das consultas feitas antes do primeiro áudio.

Token, voz, regra de roteamento e dicionário custam de 30 a 45 ms por fala em sequência
(`docs/resultados/consultas-ws.md`). Com o cache, a fala seguinte do mesmo cliente não
vai ao banco.

Vale por processo. Qualquer escrita nas rotas de admin limpa tudo no processo que a
atendeu; nas outras réplicas a mudança vale no máximo depois de `QUERY_CACHE_TTL_S`
(revogação de token incluída). `QUERY_CACHE_TTL_S=0` desliga.
"""

from __future__ import annotations

import functools
import time
from collections.abc import Awaitable, Callable

from kvoice.settings import get_settings

_MAX_ITENS = 10_000
_caches: list[dict[object, tuple[float, object]]] = []


def limpar_cache_de_consultas() -> None:
    for cache in _caches:
        cache.clear()


def em_cache[**P, R](fn: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
    """Guarda o resultado (inclusive None) por argumentos, pela validade configurada."""
    cache: dict[object, tuple[float, object]] = {}
    _caches.append(cache)

    @functools.wraps(fn)
    async def envolvida(*args: P.args, **kwargs: P.kwargs) -> R:
        ttl = get_settings().query_cache_ttl_s
        if ttl <= 0:
            return await fn(*args, **kwargs)
        chave = (args, tuple(sorted(kwargs.items())))
        agora = time.monotonic()
        guardado = cache.get(chave)
        if guardado is not None and guardado[0] > agora:
            return guardado[1]  # type: ignore[return-value]
        valor = await fn(*args, **kwargs)
        if len(cache) >= _MAX_ITENS:
            cache.clear()
        cache[chave] = (agora + ttl, valor)
        return valor

    return envolvida
