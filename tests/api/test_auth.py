"""Testes da autenticação por token (sem banco)."""

from kvoice.api.auth import gerar_token, hash_token


def test_hash_token_e_hexdigest_64_chars() -> None:
    h = hash_token("qualquer-token")
    assert len(h) == 64
    assert all(c in "0123456789abcdef" for c in h)


def test_hash_deterministico() -> None:
    assert hash_token("abc") == hash_token("abc")


def test_tokens_diferentes_produzem_hashes_diferentes() -> None:
    assert hash_token("token-a") != hash_token("token-b")


def test_gerar_token_retorna_string_nao_vazia() -> None:
    t = gerar_token()
    assert isinstance(t, str) and len(t) > 20


def test_gerar_token_aleatorio() -> None:
    assert gerar_token() != gerar_token()


def test_hash_nao_e_o_token_original() -> None:
    t = gerar_token()
    assert hash_token(t) != t
