"""Valida a estrutura de bench/frases.yaml sem precisar de GPU ou numpy."""

from pathlib import Path

import pytest
import yaml

FRASES_PATH = Path(__file__).parent.parent.parent / "bench" / "frases.yaml"
CAMPOS_OBRIGATORIOS = {"id", "texto", "categoria"}


@pytest.fixture(scope="module")
def frases() -> list[dict[str, str]]:
    with FRASES_PATH.open(encoding="utf-8") as f:
        dados = yaml.safe_load(f)
    return dados["frases"]  # type: ignore[return-value]


def test_arquivo_existe() -> None:
    assert FRASES_PATH.exists(), f"Não encontrado: {FRASES_PATH}"


def test_quantidade_minima(frases: list[dict[str, str]]) -> None:
    assert len(frases) >= 50, f"Esperado ≥ 50 frases, encontrado {len(frases)}"


def test_campos_obrigatorios(frases: list[dict[str, str]]) -> None:
    for frase in frases:
        ausentes = CAMPOS_OBRIGATORIOS - frase.keys()
        assert not ausentes, f"Campos ausentes em {frase.get('id', '?')!r}: {ausentes}"


def test_ids_unicos(frases: list[dict[str, str]]) -> None:
    ids = [f["id"] for f in frases]
    duplicados = {i for i in ids if ids.count(i) > 1}
    assert not duplicados, f"IDs duplicados: {duplicados}"


def test_textos_nao_vazios(frases: list[dict[str, str]]) -> None:
    for frase in frases:
        texto = str(frase["texto"]).strip()
        assert texto, f"Texto vazio em {frase['id']!r}"


def test_categorias_cobertas(frases: list[dict[str, str]]) -> None:
    categorias_presentes = {f["categoria"] for f in frases}
    esperadas = {
        "saudacao",
        "confirmacao",
        "normalizacao_moeda",
        "normalizacao_data",
        "normalizacao_cpf",
        "normalizacao_telefone",
        "frase_longa",
        "pergunta",
        "emocao_empatia",
        "hesitacao",
    }
    ausentes = esperadas - categorias_presentes
    assert not ausentes, f"Categorias ausentes: {ausentes}"
