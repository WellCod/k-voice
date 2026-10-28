"use strict";

/* -----------------------------------------------------------------------
   Variáveis globais carregadas por dados.js (gerado por bench/gerar_teste.py)
   const MANIFEST = { motor_ref, candidatos, condicao, testes_abx, testes_mos, testes_pref }
----------------------------------------------------------------------- */

const CHAVE_LOCAL = "kvoice_respostas";

function gerarId() {
  return Date.now().toString(36) + Math.random().toString(36).slice(2, 7);
}

const SESSAO_ID = gerarId();

// -----------------------------------------------------------------------
// Estado
// -----------------------------------------------------------------------
const estado = {
  ouvinte: "",
  fase: "intro", // intro | abx | mos | pref | fim
  idxAbx: 0,
  idxMos: 0,
  idxPref: 0,
  respostas: [],
};

// -----------------------------------------------------------------------
// Utilitários de DOM
// -----------------------------------------------------------------------
function mostrar(id) {
  document.querySelectorAll(".tela").forEach((el) => el.classList.remove("ativa"));
  document.getElementById(id).classList.add("ativa");
}

function setProgresso(fillId, labelId, atual, total) {
  document.getElementById(fillId).style.width = `${Math.round((atual / total) * 100)}%`;
  document.getElementById(labelId).textContent = `${atual} / ${total}`;
}

function limparRadios(name) {
  document.querySelectorAll(`input[name="${name}"]`).forEach((r) => (r.checked = false));
}

// -----------------------------------------------------------------------
// Intro
// -----------------------------------------------------------------------
function iniciarIntro() {
  const input = document.getElementById("ouvinte-id");
  const btn = document.getElementById("btn-iniciar");

  if (window.__semDados || typeof MANIFEST === "undefined") {
    document.getElementById("tela-intro").innerHTML =
      "<h1>dados.js não encontrado</h1>" +
      "<p>Execute <code>uv run python -m bench.gerar_teste</code> e então " +
      "sirva a pasta com <code>python -m http.server 8080</code> dentro de <em>bench/</em>.</p>";
    mostrar("tela-intro");
    return;
  }

  input.addEventListener("input", () => {
    btn.disabled = input.value.trim().length < 2;
  });

  btn.addEventListener("click", () => {
    estado.ouvinte = input.value.trim();
    iniciarAbx();
  });

  mostrar("tela-intro");
}

// -----------------------------------------------------------------------
// Fase ABX
// -----------------------------------------------------------------------
function iniciarAbx() {
  estado.fase = "abx";
  estado.idxAbx = 0;
  mostrar("tela-abx");
  renderAbx();

  document.querySelectorAll("input[name='abx-resp']").forEach((r) => {
    r.addEventListener("change", () => {
      document.getElementById("btn-abx-ok").disabled = false;
    });
  });

  document.getElementById("btn-abx-ok").addEventListener("click", confirmarAbx);
}

function renderAbx() {
  const total = MANIFEST.testes_abx.length;
  const item = MANIFEST.testes_abx[estado.idxAbx];

  setProgresso("barra-fill", "progresso-label", estado.idxAbx + 1, total);
  document.getElementById("abx-texto").textContent = item.texto;
  document.getElementById("audio-a").src = item.audio_a;
  document.getElementById("audio-b").src = item.audio_b;
  document.getElementById("audio-x").src = item.audio_x;
  limparRadios("abx-resp");
  document.getElementById("btn-abx-ok").disabled = true;
}

function confirmarAbx() {
  const item = MANIFEST.testes_abx[estado.idxAbx];
  const resposta = document.querySelector("input[name='abx-resp']:checked").value;
  // correto = 1 se o usuário escolheu o lado correto (x_eh_ref → X é A, senão X é B)
  const xEhA = item.x_eh_ref;
  const correto = (xEhA && resposta === "a") || (!xEhA && resposta === "b") ? 1 : 0;

  estado.respostas.push({
    sessao_id: SESSAO_ID,
    ouvinte_id: estado.ouvinte,
    ts: new Date().toISOString(),
    teste_id: item.id,
    frase_id: item.frase_id,
    tipo: "abx",
    motor_ref: item.motor_ref,
    motor_candidato: item.motor_candidato,
    audio_condicao: MANIFEST.condicao,
    resposta,
    correto,
  });

  salvarLocal();

  estado.idxAbx += 1;
  if (estado.idxAbx < MANIFEST.testes_abx.length) {
    renderAbx();
  } else {
    iniciarMos();
  }
}

// -----------------------------------------------------------------------
// Fase MOS
// -----------------------------------------------------------------------
function iniciarMos() {
  estado.fase = "mos";
  estado.idxMos = 0;
  mostrar("tela-mos");
  renderMos();

  document.querySelectorAll("input[name='mos-resp']").forEach((r) => {
    r.addEventListener("change", () => {
      document.getElementById("btn-mos-ok").disabled = false;
    });
  });

  document.getElementById("btn-mos-ok").addEventListener("click", confirmarMos);
}

function renderMos() {
  const total = MANIFEST.testes_mos.length;
  const item = MANIFEST.testes_mos[estado.idxMos];

  setProgresso("mos-barra-fill", "mos-progresso-label", estado.idxMos + 1, total);
  document.getElementById("mos-texto").textContent = item.texto;
  document.getElementById("audio-mos").src = item.audio;
  limparRadios("mos-resp");
  document.getElementById("btn-mos-ok").disabled = true;
}

function confirmarMos() {
  const item = MANIFEST.testes_mos[estado.idxMos];
  const resposta = document.querySelector("input[name='mos-resp']:checked").value;

  estado.respostas.push({
    sessao_id: SESSAO_ID,
    ouvinte_id: estado.ouvinte,
    ts: new Date().toISOString(),
    teste_id: item.id,
    frase_id: item.frase_id,
    tipo: "mos",
    motor_ref: MANIFEST.motor_ref,
    motor_candidato: item.motor,
    audio_condicao: MANIFEST.condicao,
    resposta,
    correto: "",
  });

  salvarLocal();

  estado.idxMos += 1;
  if (estado.idxMos < MANIFEST.testes_mos.length) {
    renderMos();
  } else {
    iniciarPref();
  }
}

// -----------------------------------------------------------------------
// Fase Preferência
// -----------------------------------------------------------------------
function iniciarPref() {
  estado.fase = "pref";
  estado.idxPref = 0;
  mostrar("tela-pref");
  renderPref();

  document.querySelectorAll("input[name='pref-resp']").forEach((r) => {
    r.addEventListener("change", () => {
      document.getElementById("btn-pref-ok").disabled = false;
    });
  });

  document.getElementById("btn-pref-ok").addEventListener("click", confirmarPref);
}

function renderPref() {
  const total = MANIFEST.testes_pref.length;
  const item = MANIFEST.testes_pref[estado.idxPref];

  setProgresso("pref-barra-fill", "pref-progresso-label", estado.idxPref + 1, total);
  document.getElementById("pref-texto").textContent = item.texto;
  document.getElementById("audio-pa").src = item.audio_a;
  document.getElementById("audio-pb").src = item.audio_b;
  limparRadios("pref-resp");
  document.getElementById("btn-pref-ok").disabled = true;
}

function confirmarPref() {
  const item = MANIFEST.testes_pref[estado.idxPref];
  const ladoEscolhido = document.querySelector("input[name='pref-resp']:checked").value;
  // a_eh_ref=true → A=ref, B=candidato
  const preferiu_ref =
    (item.a_eh_ref && ladoEscolhido === "a") || (!item.a_eh_ref && ladoEscolhido === "b");

  estado.respostas.push({
    sessao_id: SESSAO_ID,
    ouvinte_id: estado.ouvinte,
    ts: new Date().toISOString(),
    teste_id: item.id,
    frase_id: item.frase_id,
    tipo: "preferencia",
    motor_ref: item.motor_ref,
    motor_candidato: item.motor_candidato,
    audio_condicao: MANIFEST.condicao,
    resposta: preferiu_ref ? "ref" : "candidato",
    correto: "",
  });

  salvarLocal();

  estado.idxPref += 1;
  if (estado.idxPref < MANIFEST.testes_pref.length) {
    renderPref();
  } else {
    mostrarFim();
  }
}

// -----------------------------------------------------------------------
// Fim
// -----------------------------------------------------------------------
function mostrarFim() {
  estado.fase = "fim";
  mostrar("tela-fim");

  const abx = estado.respostas.filter((r) => r.tipo === "abx");
  const mos = estado.respostas.filter((r) => r.tipo === "mos");
  const pref = estado.respostas.filter((r) => r.tipo === "preferencia");
  const acertos = abx.filter((r) => r.correto === 1).length;

  document.getElementById("resumo").innerHTML =
    `<p>Respostas registradas: <strong>${estado.respostas.length}</strong></p>` +
    `<p>ABX: ${abx.length} respostas — acertos: ${acertos} (${((acertos / (abx.length || 1)) * 100).toFixed(1)}%)</p>` +
    `<p>MOS: ${mos.length} avaliações</p>` +
    `<p>Preferência: ${pref.length} respostas</p>`;

  document.getElementById("btn-csv").addEventListener("click", exportarCsv);
}

// -----------------------------------------------------------------------
// Persistência e exportação
// -----------------------------------------------------------------------
function salvarLocal() {
  try {
    localStorage.setItem(CHAVE_LOCAL, JSON.stringify(estado.respostas));
  } catch (_) {}
}

const COLUNAS = [
  "sessao_id", "ouvinte_id", "ts", "teste_id", "frase_id", "tipo",
  "motor_ref", "motor_candidato", "audio_condicao", "resposta", "correto",
];

function exportarCsv() {
  const linhas = [COLUNAS.join(",")];
  for (const r of estado.respostas) {
    linhas.push(COLUNAS.map((c) => JSON.stringify(String(r[c] ?? ""))).join(","));
  }
  const blob = new Blob([linhas.join("\n")], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `respostas_${estado.ouvinte || "ouvinte"}_${SESSAO_ID}.csv`;
  a.click();
  URL.revokeObjectURL(url);
}

// -----------------------------------------------------------------------
// Bootstrap
// -----------------------------------------------------------------------
document.addEventListener("DOMContentLoaded", iniciarIntro);
