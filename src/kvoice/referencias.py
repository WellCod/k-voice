"""Áudio de referência de clonagem cifrado em repouso (ADR-0007).

O arquivo em disco é um token Fernet (AES-128-CBC + HMAC-SHA256) com a chave de
REFERENCE_AUDIO_KEY. Os motores só aceitam caminho de arquivo, então a clonagem
decifra para um arquivo temporário, legível só pelo processo, apagado ao fim da geração.
"""

from __future__ import annotations

import hashlib
import logging
import os
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from cryptography.fernet import Fernet

from kvoice.settings import get_settings

_log = logging.getLogger(__name__)
_WAV = b"RIFF"


class ChaveAusente(RuntimeError):
    pass


def _fernet() -> Fernet:
    chave = get_settings().reference_audio_key
    if not chave:
        raise ChaveAusente(
            "REFERENCE_AUDIO_KEY não configurada; gere com "
            '`uv run python -c "from cryptography.fernet import Fernet; '
            'print(Fernet.generate_key().decode())"`'
        )
    return Fernet(chave.encode())


def exigir_chave() -> None:
    _fernet()


def cifrar(dados: bytes) -> bytes:
    return _fernet().encrypt(dados)


def decifrar(dados: bytes) -> bytes:
    if dados.startswith(_WAV):
        # Gravado antes da cifra; scripts/cifrar_referencias.py migra.
        _log.warning("áudio de referência sem cifra em disco")
        return dados
    return _fernet().decrypt(dados)


def _dir_temp() -> Path:
    d = Path(tempfile.gettempdir()) / "kvoice-refs"
    d.mkdir(mode=0o700, exist_ok=True)
    return d


@contextmanager
def arquivo_decifrado(caminho: str) -> Iterator[str]:
    """Caminho de um WAV decifrado que existe só dentro do bloco.

    O nome é fixo por referência: o faster-qwen3-tts guarda o prompt da voz em memória
    indexado pelo caminho e só relê o arquivo quando muda de voz.
    """
    destino = _dir_temp() / (hashlib.sha256(caminho.encode()).hexdigest()[:32] + ".wav")
    dados = decifrar(Path(caminho).read_bytes())
    fd = os.open(destino, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, dados)
    finally:
        os.close(fd)
    try:
        yield str(destino)
    finally:
        destino.unlink(missing_ok=True)
