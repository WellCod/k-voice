from __future__ import annotations

import asyncio
import json
import pathlib
import uuid
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, Form, HTTPException, Request, UploadFile, status
from sqlalchemy import select

from kvoice.api.auth import gerar_token, hash_token
from kvoice.api.deps import DbSession, _exigir_scope
from kvoice.api.schemas import (
    ClientCreate,
    ClientResponse,
    PronunciationEntryCreate,
    PronunciationEntryResponse,
    RoutingRuleCreate,
    RoutingRuleResponse,
    TokenCreate,
    TokenCreated,
    TokenResponse,
    VoiceConsentResponse,
    VoiceCreate,
    VoicePatch,
    VoiceResponse,
)
from kvoice.audio import preprocess_ref_audio
from kvoice.cache_consultas import limpar_cache_de_consultas
from kvoice.db.models import (
    ApiToken,
    Client,
    PronunciationEntry,
    RoutingRule,
    Voice,
    VoiceConsent,
    VoiceOrigin,
)
from kvoice.engine.cache import limpar_caches_de_audio
from kvoice.referencias import ChaveAusente, cifrar, exigir_chave

# Diretório local para áudio de referência (dev; produção usa S3)
_REFS_DIR = pathlib.Path(__file__).parent.parent.parent.parent.parent / "data" / "references"

_MAX_REF_BYTES = 25 * 1024 * 1024


async def _limpar_cache_em_escrita(request: Request) -> AsyncIterator[None]:
    """Dependência do roteador: limpa o cache de consultas antes e depois de cada escrita.

    Token revogado, voz, regra ou dicionário mudados valem na hora neste processo. A
    limpeza depois da rota cobre a leitura concorrente que repovoou o cache com o valor
    antigo antes do commit. Nas outras réplicas vale a validade (`QUERY_CACHE_TTL_S`).
    """
    escrita = request.method not in ("GET", "HEAD", "OPTIONS")
    if escrita:
        limpar_cache_de_consultas()
    yield
    if escrita:
        limpar_cache_de_consultas()


router = APIRouter(
    prefix="/admin", tags=["admin"], dependencies=[Depends(_limpar_cache_em_escrita)]
)
_admin = Depends(_exigir_scope("admin"))


@router.post(
    "/clients",
    response_model=ClientResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[_admin],
)
async def criar_cliente(body: ClientCreate, db: DbSession) -> Client:
    client = Client(name=body.name)
    db.add(client)
    await db.commit()
    await db.refresh(client)
    return client


@router.get("/clients", response_model=list[ClientResponse], dependencies=[_admin])
async def listar_clientes(db: DbSession) -> list[Client]:
    result = await db.execute(select(Client).order_by(Client.created_at.desc()))
    return list(result.scalars().all())


@router.post(
    "/clients/{client_id}/tokens",
    response_model=TokenCreated,
    status_code=status.HTTP_201_CREATED,
    dependencies=[_admin],
)
async def criar_token(client_id: uuid.UUID, body: TokenCreate, db: DbSession) -> TokenCreated:
    """Gera um token para o cliente; o texto do token só aparece nesta resposta."""
    client = await db.get(Client, client_id)
    if client is None or not client.is_active:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cliente não encontrado")
    token_em_texto = gerar_token()
    # No banco fica só o hash (ver CLAUDE.md, regras críticas).
    token = ApiToken(
        client_id=client_id,
        name=body.name,
        token_hash=hash_token(token_em_texto),
        scopes=",".join(body.scopes),
    )
    db.add(token)
    await db.commit()
    await db.refresh(token)
    return TokenCreated(id=token.id, name=token.name, token=token_em_texto, scopes=body.scopes)


@router.get(
    "/clients/{client_id}/tokens",
    response_model=list[TokenResponse],
    dependencies=[_admin],
)
async def listar_tokens(client_id: uuid.UUID, db: DbSession) -> list[ApiToken]:
    result = await db.execute(
        select(ApiToken).where(ApiToken.client_id == client_id).order_by(ApiToken.created_at.desc())
    )
    return list(result.scalars().all())


@router.delete(
    "/clients/{client_id}/tokens/{token_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[_admin],
)
async def revogar_token(client_id: uuid.UUID, token_id: uuid.UUID, db: DbSession) -> None:
    """Desativa o token em vez de apagar; a autenticação passa a recusá-lo."""
    token = await db.get(ApiToken, token_id)
    if token is None or token.client_id != client_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Token não encontrado")
    token.is_active = False
    await db.commit()


@router.post(
    "/voices",
    response_model=VoiceResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[_admin],
)
async def criar_voz(body: VoiceCreate, db: DbSession) -> Voice:
    """Cadastra a voz; com `client_id` ela fica privada desse cliente, sem ele é catálogo."""
    existente = await db.get(Voice, body.id)
    if existente is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="ID de voz já existe")
    if body.client_id is not None and await db.get(Client, body.client_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cliente não encontrado")
    voice = Voice(
        id=body.id,
        name=body.name,
        gender=body.gender,
        age_range=body.age_range,
        style=body.style,
        language=body.language,
        origin=body.origin,
        model_id=body.model_id,
        style_prompt=body.style_prompt,
        elevenlabs_voice_id=body.elevenlabs_voice_id,
        client_id=body.client_id,
    )
    db.add(voice)
    await db.commit()
    await db.refresh(voice)
    return voice


@router.patch(
    "/voices/{voice_id}",
    response_model=VoiceResponse,
    dependencies=[_admin],
)
async def atualizar_voz(voice_id: str, body: VoicePatch, db: DbSession) -> Voice:
    """Atualiza só os campos enviados.

    Nos campos de texto, ausente (None) mantém o valor e string vazia apaga. Em
    `client_id`, null é valor válido (volta ao catálogo), então o que distingue "não
    mexer" de "remover o dono" é o campo ter vindo no corpo.
    """
    voice = await db.get(Voice, voice_id)
    if voice is None or not voice.is_active:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Voz não encontrada")
    if body.style_prompt is not None:
        voice.style_prompt = body.style_prompt or None
    if body.model_id is not None:
        voice.model_id = body.model_id or None
    if body.elevenlabs_voice_id is not None:
        voice.elevenlabs_voice_id = body.elevenlabs_voice_id or None
    if "client_id" in body.model_fields_set:
        if body.client_id is not None and await db.get(Client, body.client_id) is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Cliente não encontrado"
            )
        voice.client_id = body.client_id
    await db.commit()
    limpar_caches_de_audio()  # instrução ou speaker novos mudam o áudio da voz
    await db.refresh(voice)
    return voice


@router.post(
    "/voices/{voice_id}/reference-audio",
    response_model=VoiceConsentResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[_admin],
)
async def upload_audio_referencia(
    voice_id: str,
    audio: UploadFile,
    db: DbSession,
    consenter_name: str = Form(...),
    consenter_email: str = Form(...),
    ref_text: str = Form(...),
) -> VoiceConsent:
    """Faz upload do áudio de referência e registra consentimento (ADR-0007)."""
    voice = await db.get(Voice, voice_id)
    if voice is None or not voice.is_active:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Voz não encontrada")
    try:
        exigir_chave()
    except ChaveAusente as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc

    audio_bytes = await audio.read(_MAX_REF_BYTES + 1)
    if len(audio_bytes) > _MAX_REF_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Áudio de referência acima de 25 MB",
        )
    if len(audio_bytes) < 1000:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Áudio muito curto")

    # Determina extensão real a partir do nome do arquivo enviado
    original_name = audio.filename or "ref.webm"
    extensao = original_name.rsplit(".", 1)[-1].lower() if "." in original_name else "webm"
    if extensao not in {"wav", "mp3", "ogg", "webm", "m4a", "flac"}:
        extensao = "webm"

    # Normaliza loudness, remove silêncio e converte para WAV 16 kHz mono
    try:
        audio_bytes, duration_s = await asyncio.to_thread(
            preprocess_ref_audio, audio_bytes, extensao
        )
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Falha ao processar áudio: {exc}",
        ) from exc

    if duration_s < 5.0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Áudio de fala limpa muito curto ({duration_s:.1f}s). Mínimo: 5 segundos.",
        )

    # WAV normalizado e cifrado em disco local (produção: S3 em kvoice.storage)
    _REFS_DIR.mkdir(parents=True, exist_ok=True)
    file_key = f"{voice_id}/{uuid.uuid4()}.wav"
    local_path = _REFS_DIR / file_key
    local_path.parent.mkdir(parents=True, exist_ok=True)
    local_path.write_bytes(cifrar(audio_bytes))

    voice.origin = VoiceOrigin.clone
    voice.ref_audio_key = str(local_path)
    voice.ref_text = ref_text

    consent = VoiceConsent(
        voice_id=voice_id,
        consenter_name=consenter_name,
        consenter_email=consenter_email,
        audio_key=file_key,
    )
    db.add(consent)
    await db.commit()
    limpar_caches_de_audio()  # referência nova: o áudio em cache é da voz antiga
    await db.refresh(consent)
    return consent


@router.put(
    "/clients/{client_id}/routing",
    response_model=RoutingRuleResponse,
    dependencies=[_admin],
)
async def upsert_regra_roteamento(
    client_id: uuid.UUID, body: RoutingRuleCreate, db: DbSession
) -> RoutingRule:
    """Cria ou substitui a regra ativa do cliente (no máximo uma ativa por cliente)."""
    client = await db.get(Client, client_id)
    if client is None or not client.is_active:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cliente não encontrado")

    result = await db.execute(
        select(RoutingRule)
        .where(RoutingRule.client_id == client_id, RoutingRule.is_active.is_(True))
        .limit(1)
    )
    rule = result.scalar_one_or_none()

    # O mapa de vozes k-voice -> ElevenLabs é guardado como JSON em texto.
    mapa_json = json.dumps(body.voice_mapping) if body.voice_mapping is not None else None

    if rule is None:
        rule = RoutingRule(
            client_id=client_id,
            mode=body.mode,
            kvoice_pct=body.kvoice_pct,
            voice_mapping=mapa_json,
        )
        db.add(rule)
    else:
        rule.mode = body.mode
        rule.kvoice_pct = body.kvoice_pct
        rule.voice_mapping = mapa_json

    await db.commit()
    await db.refresh(rule)
    return rule


@router.get(
    "/clients/{client_id}/routing",
    response_model=RoutingRuleResponse,
    dependencies=[_admin],
)
async def buscar_regra_roteamento(client_id: uuid.UUID, db: DbSession) -> RoutingRule:
    result = await db.execute(
        select(RoutingRule)
        .where(RoutingRule.client_id == client_id, RoutingRule.is_active.is_(True))
        .limit(1)
    )
    rule = result.scalar_one_or_none()
    if rule is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Regra de roteamento não encontrada"
        )
    return rule


@router.delete(
    "/clients/{client_id}/routing",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[_admin],
)
async def remover_regra_roteamento(client_id: uuid.UUID, db: DbSession) -> None:
    """Desativa a regra; o cliente volta ao padrão (só k-voice)."""
    result = await db.execute(
        select(RoutingRule)
        .where(RoutingRule.client_id == client_id, RoutingRule.is_active.is_(True))
        .limit(1)
    )
    rule = result.scalar_one_or_none()
    if rule is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Regra de roteamento não encontrada"
        )
    rule.is_active = False
    await db.commit()


# ---------------------------------------------------------------------------
# Dicionário de pronúncia
# ---------------------------------------------------------------------------


@router.post(
    "/clients/{client_id}/pronunciation",
    response_model=PronunciationEntryResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[_admin],
)
async def criar_entrada_pronuncia(
    client_id: uuid.UUID, body: PronunciationEntryCreate, db: DbSession
) -> PronunciationEntry:
    client = await db.get(Client, client_id)
    if client is None or not client.is_active:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cliente não encontrado")
    entry = PronunciationEntry(
        client_id=client_id,
        term=body.term,
        expansion=body.expansion,
        is_regex=body.is_regex,
    )
    db.add(entry)
    await db.commit()
    await db.refresh(entry)
    return entry


@router.get(
    "/clients/{client_id}/pronunciation",
    response_model=list[PronunciationEntryResponse],
    dependencies=[_admin],
)
async def listar_entradas_pronuncia(
    client_id: uuid.UUID, db: DbSession
) -> list[PronunciationEntry]:
    result = await db.execute(
        select(PronunciationEntry)
        .where(PronunciationEntry.client_id == client_id)
        .order_by(PronunciationEntry.term)
    )
    return list(result.scalars().all())


@router.post(
    "/pronunciation",
    response_model=PronunciationEntryResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[_admin],
)
async def criar_entrada_pronuncia_global(
    body: PronunciationEntryCreate, db: DbSession
) -> PronunciationEntry:
    """Entrada sem cliente: vale para todos; a literal do cliente com o mesmo termo vence."""
    entry = PronunciationEntry(
        client_id=None,
        term=body.term,
        expansion=body.expansion,
        is_regex=body.is_regex,
    )
    db.add(entry)
    await db.commit()
    await db.refresh(entry)
    return entry


@router.get(
    "/pronunciation",
    response_model=list[PronunciationEntryResponse],
    dependencies=[_admin],
)
async def listar_entradas_pronuncia_global(db: DbSession) -> list[PronunciationEntry]:
    result = await db.execute(
        select(PronunciationEntry)
        .where(PronunciationEntry.client_id.is_(None))
        .order_by(PronunciationEntry.term)
    )
    return list(result.scalars().all())


@router.delete(
    "/pronunciation/{entry_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[_admin],
)
async def remover_entrada_pronuncia(entry_id: uuid.UUID, db: DbSession) -> None:
    entry = await db.get(PronunciationEntry, entry_id)
    if entry is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Entrada não encontrada")
    await db.delete(entry)
    await db.commit()
