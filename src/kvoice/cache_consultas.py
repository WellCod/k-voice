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
    """Esvazia o cache de todas as funções decoradas com `em_cache` neste processo."""
    for cache in _caches:
        cache.clear()


def em_cache[**P, R](funcao: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
    """Guarda o resultado (inclusive None) por argumentos, pela validade configurada."""
    # Cada função decorada tem seu dicionário: (expira_em, resultado) por argumentos.
    cache: dict[object, tuple[float, object]] = {}
    _caches.append(cache)

    @functools.wraps(funcao)
    async def envolvida(*args: P.args, **kwargs: P.kwargs) -> R:
        # Lida a cada chamada para que os testes e o ambiente possam mudar a validade.
        validade_s = get_settings().query_cache_ttl_s
        if validade_s <= 0:
            return await funcao(*args, **kwargs)
        chave = (args, tuple(sorted(kwargs.items())))
        agora = time.monotonic()
        guardado = cache.get(chave)
        if guardado is not None and guardado[0] > agora:
            return guardado[1]  # type: ignore[return-value]
        valor = await funcao(*args, **kwargs)
        # Teto de memória simples: cheio, recomeça do zero em vez de manter ordem de uso.
        if len(cache) >= _MAX_ITENS:
            cache.clear()
        cache[chave] = (agora + validade_s, valor)
        return valor

    return envolvida
