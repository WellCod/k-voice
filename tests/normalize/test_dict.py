"""Testes do dicionário de pronúncia: apply_dict e load_dict."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from kvoice.normalize._dict import PronEntry, apply_dict, load_dict

# ---------------------------------------------------------------------------
# apply_dict
# ---------------------------------------------------------------------------


def test_apply_dict_literal() -> None:
    """Substituição literal simples."""
    entries: list[PronEntry] = [("PIX", "pix", False)]
    assert apply_dict("Pague via PIX agora.", entries) == "Pague via pix agora."


def test_apply_dict_regex() -> None:
    """Substituição via regex."""
    entries: list[PronEntry] = [(r"\bSPF\s*\d+\b", "protetor solar", True)]
    assert apply_dict("Use SPF 50 diariamente.", entries) == "Use protetor solar diariamente."


def test_apply_dict_literal_antes_regex() -> None:
    """Literais aplicados antes dos regex na lista."""
    entries: list[PronEntry] = [
        ("FGTS", "fundo de garantia", False),
        (r"\bFGTS\b", "FGTS ignorado", True),
    ]
    result = apply_dict("Saque do FGTS.", entries)
    assert result == "Saque do fundo de garantia."


def test_apply_dict_vazio() -> None:
    """Lista vazia não altera o texto."""
    assert apply_dict("texto original", []) == "texto original"


def test_apply_dict_multiplos_termos() -> None:
    """Múltiplos literais aplicados em sequência."""
    entries: list[PronEntry] = [
        ("CPF", "c p f", False),
        ("CNPJ", "c n p j", False),
    ]
    result = apply_dict("CPF ou CNPJ", entries)
    assert result == "c p f ou c n p j"


# ---------------------------------------------------------------------------
# load_dict
# ---------------------------------------------------------------------------


def _make_entry(
    term: str, expansion: str, is_regex: bool, client_id: uuid.UUID | None
) -> MagicMock:
    e = MagicMock()
    e.term = term
    e.expansion = expansion
    e.is_regex = is_regex
    e.client_id = client_id
    return e


async def test_load_dict_global_apenas() -> None:
    """Entradas globais são carregadas corretamente."""
    cid = uuid.uuid4()
    global_entry = _make_entry("CPF", "c p f", False, None)

    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [global_entry]

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_result)

    mock_cm = AsyncMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_db)
    mock_cm.__aexit__ = AsyncMock(return_value=False)

    with patch("kvoice.normalize._dict.session_factory") as mock_sf:
        mock_sf.return_value.return_value = mock_cm
        entries = await load_dict(cid)

    assert ("CPF", "c p f", False) in entries


async def test_load_dict_cliente_sobrepoe_global() -> None:
    """Entrada do cliente sobrepõe global para o mesmo termo."""
    cid = uuid.uuid4()
    global_entry = _make_entry("PIX", "errado", False, None)
    client_entry = _make_entry("PIX", "pix", False, cid)

    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [global_entry, client_entry]

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_result)

    mock_cm = AsyncMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_db)
    mock_cm.__aexit__ = AsyncMock(return_value=False)

    with patch("kvoice.normalize._dict.session_factory") as mock_sf:
        mock_sf.return_value.return_value = mock_cm
        entries = await load_dict(cid)

    plain = {term: exp for term, exp, is_regex in entries if not is_regex}
    assert plain["PIX"] == "pix"


async def test_load_dict_regex_separado() -> None:
    """Entradas de regex ficam no final da lista."""
    cid = uuid.uuid4()
    regex_entry = _make_entry(r"\bCNPJ\b", "c n p j", True, None)
    plain_entry = _make_entry("CPF", "c p f", False, None)

    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [plain_entry, regex_entry]

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_result)

    mock_cm = AsyncMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_db)
    mock_cm.__aexit__ = AsyncMock(return_value=False)

    with patch("kvoice.normalize._dict.session_factory") as mock_sf:
        mock_sf.return_value.return_value = mock_cm
        entries = await load_dict(cid)

    is_regex_flags = [is_regex for _, _, is_regex in entries]
    # todos os False (literais) antes dos True (regex)
    assert is_regex_flags == sorted(is_regex_flags)
