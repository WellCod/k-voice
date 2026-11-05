from __future__ import annotations

import importlib.util
import types
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from cryptography.fernet import Fernet
from fastapi import FastAPI
from fastapi.testclient import TestClient

from kvoice import referencias
from kvoice.referencias import ChaveAusente, arquivo_decifrado, cifrar, decifrar

_WAV = b"RIFF" + b"\x00" * 2000
_OGG = b"OggS\x00\x02" + b"\x00" * 2000


@pytest.fixture()
def chave(monkeypatch: pytest.MonkeyPatch) -> str:
    k = Fernet.generate_key().decode()
    monkeypatch.setattr(
        referencias, "get_settings", lambda: types.SimpleNamespace(reference_audio_key=k)
    )
    return k


@pytest.fixture()
def sem_chave(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        referencias, "get_settings", lambda: types.SimpleNamespace(reference_audio_key="")
    )


def test_cifra_e_decifra(chave: str) -> None:
    cifrado = cifrar(_WAV)
    assert b"RIFF" not in cifrado
    assert decifrar(cifrado) == _WAV


def test_sem_chave_recusa_cifrar(sem_chave: None) -> None:
    with pytest.raises(ChaveAusente):
        cifrar(_WAV)


def test_wav_antigo_sem_cifra_ainda_le(sem_chave: None) -> None:
    assert decifrar(_WAV) == _WAV


def test_ogg_antigo_sem_cifra_ainda_le(sem_chave: None) -> None:
    assert decifrar(_OGG) == _OGG


def test_temporario_mantem_extensao_original(chave: str, tmp_path: Path) -> None:
    origem = tmp_path / "ref.ogg"
    origem.write_bytes(cifrar(_OGG))
    with arquivo_decifrado(str(origem)) as caminho:
        assert caminho.endswith(".ogg")
        assert Path(caminho).read_bytes() == _OGG


def test_arquivo_decifrado_existe_so_dentro_do_bloco(chave: str, tmp_path: Path) -> None:
    origem = tmp_path / "ref.wav"
    origem.write_bytes(cifrar(_WAV))

    with arquivo_decifrado(str(origem)) as caminho:
        assert Path(caminho).read_bytes() == _WAV
        assert Path(caminho) != origem
    assert not Path(caminho).exists()

    with pytest.raises(RuntimeError), arquivo_decifrado(str(origem)) as caminho:
        raise RuntimeError("falha na geração")
    assert not Path(caminho).exists()

    # Nome estável por referência: o faster-qwen3-tts indexa o prompt da voz pelo caminho.
    with arquivo_decifrado(str(origem)) as de_novo:
        assert de_novo == caminho


def test_script_cifra_pasta_e_e_idempotente(chave: str, tmp_path: Path) -> None:
    caminho = Path(__file__).parents[1] / "scripts" / "cifrar_referencias.py"
    spec = importlib.util.spec_from_file_location("cifrar_referencias", caminho)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    (tmp_path / "v1").mkdir()
    (tmp_path / "v1" / "a.wav").write_bytes(_WAV)
    (tmp_path / "v1" / "b.wav").write_bytes(cifrar(_WAV))
    (tmp_path / "v1" / "c.ogg").write_bytes(_OGG)
    (tmp_path / "v1" / "d.wav").write_bytes(_OGG)  # OGG com extensão .wav, como no legado

    assert mod.cifrar_pasta(tmp_path) == (3, 1)
    assert mod.cifrar_pasta(tmp_path) == (0, 4)
    assert decifrar((tmp_path / "v1" / "a.wav").read_bytes()) == _WAV
    assert decifrar((tmp_path / "v1" / "c.ogg").read_bytes()) == _OGG
    assert decifrar((tmp_path / "v1" / "d.wav").read_bytes()) == _OGG


def _app_upload(voz: Any) -> FastAPI:
    from kvoice.api.deps import _autenticar, get_db
    from kvoice.api.routers import admin

    app = FastAPI()
    app.include_router(admin.router)
    token = types.SimpleNamespace(has_scope=lambda _s: True)

    async def _auth() -> tuple[Any, Any]:
        return types.SimpleNamespace(id=uuid.uuid4()), token

    async def _db() -> Any:
        db = AsyncMock()
        db.get = AsyncMock(return_value=voz)
        db.add = MagicMock()

        async def _refresh(obj: Any) -> None:
            obj.id = uuid.uuid4()
            obj.created_at = datetime.now(UTC)

        db.refresh = _refresh
        yield db

    app.dependency_overrides[_autenticar] = _auth
    app.dependency_overrides[get_db] = _db
    return app


def _voz() -> Any:
    return types.SimpleNamespace(
        id="v_clone", is_active=True, origin=None, ref_audio_key=None, ref_text=None
    )


_FORM = {"consenter_name": "Ana", "consenter_email": "ana@exemplo.com", "ref_text": "Olá."}


def test_upload_sem_chave_e_recusado(sem_chave: None) -> None:
    with TestClient(_app_upload(_voz())) as client:
        resp = client.post(
            "/admin/voices/v_clone/reference-audio",
            data=_FORM,
            files={"audio": ("ref.wav", _WAV, "audio/wav")},
        )
    assert resp.status_code == 503
    assert "REFERENCE_AUDIO_KEY" in resp.json()["detail"]


def test_upload_grava_referencia_cifrada(
    chave: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from kvoice.api.routers import admin

    monkeypatch.setattr(admin, "_REFS_DIR", tmp_path)
    voz = _voz()
    with (
        patch.object(admin, "preprocess_ref_audio", return_value=(_WAV, 8.0)),
        TestClient(_app_upload(voz)) as client,
    ):
        resp = client.post(
            "/admin/voices/v_clone/reference-audio",
            data=_FORM,
            files={"audio": ("ref.wav", _WAV, "audio/wav")},
        )

    assert resp.status_code == 201, resp.text
    gravado = Path(voz.ref_audio_key).read_bytes()
    assert not gravado.startswith(b"RIFF")
    assert decifrar(gravado) == _WAV
