# -*- coding: utf-8 -*-
"""
Citizen Assist AI - protótipo de assistente de orientação cidadã (interface textual).

Execução:  python src/sistema.py
Testes:    python src/sistema.py --testes

AVISO: protótipo educacional. NÃO é canal oficial de nenhum órgão público e não
coleta dados pessoais. As orientações vêm de uma base resumida (data/base.json)
e sempre indicam a fonte consultada.

Organização do arquivo:
  1. Configurações e modelos de prompt
  2. Leitura e validação da base (JSON)
  3. Texto: normalização e tokenização
  4. Índices, grafo de assuntos e Dijkstra
  5. Estratégias de busca (A: palavras-chave | B: TF-IDF + cosseno)
  6. Decisão da resposta (condicionais e tratamento de limites)
  7. Formatação das respostas (modelos M1 e M2)
  8. Sessão interativa (menu, navegação)
  9. Testes, indicadores e roteiro de usabilidade
"""
import csv
import heapq
import json
import math
import os
import re
import sys
import time
import unicodedata
from collections import Counter, defaultdict
from itertools import combinations

# --------------------------------------------------------------------------
# 1. CONFIGURAÇÕES E MODELOS DE PROMPT
# --------------------------------------------------------------------------
RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CAMINHO_BASE = os.path.join(RAIZ, "data", "base.json")
CAMINHO_TESTES = os.path.join(RAIZ, "data", "testes.json")
CAMINHO_RESULTADOS = os.path.join(RAIZ, "docs", "resultados_testes.csv")
CAMINHO_INDICADORES = os.path.join(RAIZ, "docs", "indicadores.json")

CAMPOS_OBRIGATORIOS = ["id", "tema", "subtema", "palavras_chave", "pergunta",
                       "orientacao", "referencia", "data_verificacao"]

STOPWORDS = {
    "a", "o", "as", "os", "um", "uma", "uns", "umas", "de", "da", "do", "das", "dos",
    "em", "no", "na", "nos", "nas", "por", "para", "pra", "com", "sem", "e", "ou", "que",
    "se", "ao", "aos", "eu", "me", "meu", "minha", "meus", "minhas", "seu", "sua",
    "como", "qual", "quais", "quem", "onde", "quando", "quanto", "posso", "pode",
    "preciso", "quero", "queria", "faco", "fazer", "fazem", "tenho", "ter", "ser", "sou",
    "esta", "estou", "sobre", "ha", "ja", "mais", "muito", "isso", "isto", "essa", "esse",
    "ajuda", "informacao", "informacoes", "saber", "gostaria", "favor", "nao", "foi",
    "vai", "ir", "sao", "e", "pelo", "pela", "ate", "entre", "algum", "alguma",
}

# Limiares e regras de decisão (explicados no README)
LIMIAR_A_FRACO = 1        # busca A: pontuação mínima para considerar correspondência
LIMIAR_A_FORTE = 2        # busca A: a partir daqui a confiança é "alta"
LIMIAR_B_FRACO = 0.10     # busca B: similaridade mínima (cosseno)
LIMIAR_B_FORTE = 0.22     # busca B: a partir daqui a confiança é "alta"
RAZAO_EMPATE = 0.80       # 2º colocado >= 80% do 1º => consulta ambígua
TAMANHO_MAXIMO = 300      # caracteres aceitos em uma consulta

AVISO_NAO_OFICIAL = ("Este assistente é um protótipo educacional e NÃO é um canal oficial "
                     "de órgãos públicos. Não informe dados pessoais.")

# Modelos de prompt / instrução de resposta (documentados no README e no relatório).
# O protótipo não usa IA generativa: os modelos controlam o FORMATO e as REGRAS da
# resposta. A função montar_prompt() mostra o texto que seria enviado a um modelo externo.
MODELOS = {
    "M1": {
        "nome": "M1 - Direto",
        "papel": "Você é um assistente de orientação cidadã. Responda de forma breve.",
        "formato": "Uma frase de orientação seguida da fonte.",
        "regras": ["Use somente a base fornecida.", "Cite a fonte.",
                   "Se não houver base, diga que não sabe."],
    },
    "M2": {
        "nome": "M2 - Estruturado",
        "papel": ("Você é um assistente de orientação cidadã. Não é canal oficial de órgãos "
                  "públicos e não pede dados pessoais."),
        "formato": ("Assunto, resumo da orientação, fonte consultada, data de verificação, "
                    "aviso de confirmação quando necessário e próximos assuntos."),
        "regras": ["Use somente a base fornecida; nunca invente instruções.",
                   "Cite sempre a fonte e a data de verificação.",
                   "Avise quando for preciso confirmar requisitos atualizados.",
                   "Se não houver base suficiente, informe o limite e sugira alternativas.",
                   "Use linguagem simples e frases curtas."],
    },
}


def montar_prompt(modelo, registro, pergunta):
    """Monta o texto de instrução que seria enviado a um modelo externo (documentação)."""
    m = MODELOS[modelo]
    regras = "\n".join("- " + r for r in m["regras"])
    return (f"PAPEL: {m['papel']}\nFORMATO: {m['formato']}\nREGRAS:\n{regras}\n"
            f"BASE: {registro['orientacao']} (fonte: {registro['referencia']}, "
            f"verificado em {registro['data_verificacao']})\nPERGUNTA: {pergunta}")


# --------------------------------------------------------------------------
# 2. LEITURA E VALIDAÇÃO DA BASE
# --------------------------------------------------------------------------
class ErroBase(Exception):
    """Erro de leitura ou validação da base de conhecimento."""


def validar_registro(r):
    """Retorna a lista de problemas encontrados em um registro (vazia = válido)."""
    if not isinstance(r, dict):
        return ["registro não é um objeto"]
    problemas = []
    for campo in CAMPOS_OBRIGATORIOS:
        if campo not in r or r[campo] in (None, "", []):
            problemas.append(f"campo ausente ou vazio: {campo}")
    if not problemas:
        if not (isinstance(r["palavras_chave"], list)
                and all(isinstance(k, str) for k in r["palavras_chave"])):
            problemas.append("palavras_chave deve ser uma lista de textos")
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(r["data_verificacao"])):
            problemas.append("data_verificacao deve estar no formato AAAA-MM-DD")
        if not str(r["referencia"]).startswith("http"):
            problemas.append("referencia deve ser um endereço verificável (http...)")
    return problemas


def carregar_base(caminho=CAMINHO_BASE):
    """Lê o JSON, valida cada registro e devolve (registros_válidos, descartados, temas)."""
    if not os.path.exists(caminho):
        raise ErroBase(f"Arquivo da base não encontrado: {caminho}")
    try:
        with open(caminho, encoding="utf-8") as f:
            dados = json.load(f)
    except json.JSONDecodeError as e:
        raise ErroBase(f"O arquivo da base não é um JSON válido ({e}).")
    registros = dados.get("registros") if isinstance(dados, dict) else None
    if not registros:
        raise ErroBase("A base está vazia: nenhum registro encontrado.")
    validos, descartados, ids = [], [], set()
    for i, r in enumerate(registros):
        problemas = validar_registro(r)
        if not problemas and r["id"] in ids:
            problemas.append("id duplicado")
        if problemas:
            descartados.append((r.get("id", f"#{i}") if isinstance(r, dict) else f"#{i}", problemas))
        else:
            ids.add(r["id"])
            validos.append(r)
    if not validos:
        raise ErroBase("Nenhum registro válido na base.")
    temas = dados.get("temas") or {}
    for r in validos:  # garante que todo tema/subtema usado exista na estrutura
        t = temas.setdefault(r["tema"], {"nome": r["tema"], "descricao": "", "subtemas": {}})
        t.setdefault("subtemas", {}).setdefault(r["subtema"], r["subtema"])
    return validos, descartados, temas


# --------------------------------------------------------------------------
# 3. TEXTO
# --------------------------------------------------------------------------
def normalizar(texto):
    """minúsculas, sem acentos, só letras/números separados por espaço."""
    texto = unicodedata.normalize("NFD", str(texto).lower())
    texto = "".join(c for c in texto if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]+", " ", texto).strip()


def radical(token):
    """Stemming bem simples: remove plural final (documentos -> documento)."""
    if len(token) > 4 and token.endswith("s"):
        return token[:-1]
    return token


def tokens(texto):
    return [radical(t) for t in normalizar(texto).split()
            if t not in STOPWORDS and (len(t) > 1 or t.isdigit())]


# --------------------------------------------------------------------------
# 4. ÍNDICES, GRAFO E DIJKSTRA
# --------------------------------------------------------------------------
class Base:
    """Reúne registros e estruturas de consulta (dicionários, listas, grafo)."""

    def __init__(self, registros, temas):
        self.registros = registros
        self.temas = temas
        self.por_id = {r["id"]: r for r in registros}                 # dict: id -> registro
        self.por_tema = defaultdict(list)                               # dict: tema -> [registros]
        self.por_subtema = defaultdict(list)
        for r in registros:
            self.por_tema[r["tema"]].append(r)
            self.por_subtema[(r["tema"], r["subtema"])].append(r)
        # índice invertido das palavras-chave: token -> {ids}
        self.idx_chave = defaultdict(set)
        for r in registros:
            for kw in r["palavras_chave"]:
                for t in tokens(kw):
                    self.idx_chave[t].add(r["id"])
        self._construir_tfidf()
        self.grafo = self._construir_grafo()

    # ---- grafo de assuntos -------------------------------------------------
    def _construir_grafo(self):
        """Nós = registros. Arestas: relacionados explícitos (peso 1),
        mesmo subtema (peso 2) e mesmo tema (peso 3). Menor peso = mais próximo."""
        g = defaultdict(dict)

        def aresta(a, b, peso):
            if a != b and b in self.por_id and a in self.por_id:
                g[a][b] = min(peso, g[a].get(b, 99))
                g[b][a] = min(peso, g[b].get(a, 99))

        for r in self.registros:
            for rel in r.get("relacionados", []):
                aresta(r["id"], rel, 1)
        for a, b in combinations(self.registros, 2):
            if a["tema"] == b["tema"] and a["subtema"] == b["subtema"]:
                aresta(a["id"], b["id"], 2)
            elif a["tema"] == b["tema"]:
                aresta(a["id"], b["id"], 3)
        return g

    def dijkstra(self, origem):
        """Menor distância da origem a todos os assuntos (algoritmo de Dijkstra)."""
        dist = {origem: 0}
        fila = [(0, origem)]
        while fila:
            d, no = heapq.heappop(fila)
            if d > dist.get(no, math.inf):
                continue
            for viz, peso in self.grafo[no].items():
                nd = d + peso
                if nd < dist.get(viz, math.inf):
                    dist[viz] = nd
                    heapq.heappush(fila, (nd, viz))
        return dist

    def relacionados(self, rid, n=3):
        """Os n assuntos mais próximos de rid no grafo (desempate por id)."""
        dist = self.dijkstra(rid)
        proximos = sorted(((d, i) for i, d in dist.items() if i != rid))
        return [self.por_id[i] for _, i in proximos[:n]]

    # ---- TF-IDF ------------------------------------------------------------
    def _texto_doc(self, r):
        return " ".join([r["pergunta"], " ".join(r["palavras_chave"]) * 2,
                         r["orientacao"], r["subtema"].replace("_", " ")])

    def _construir_tfidf(self):
        docs = {r["id"]: Counter(tokens(self._texto_doc(r))) for r in self.registros}
        n = len(docs)
        df = Counter()
        for c in docs.values():
            df.update(c.keys())
        self.idf = {t: math.log((n + 1) / (df[t] + 1)) + 1 for t in df}
        self.vet = {}
        self.norma = {}
        for rid, c in docs.items():
            v = {t: f * self.idf[t] for t, f in c.items()}
            self.vet[rid] = v
            self.norma[rid] = math.sqrt(sum(x * x for x in v.values())) or 1.0


def construir_base(caminho=CAMINHO_BASE):
    registros, descartados, temas = carregar_base(caminho)
    return Base(registros, temas), descartados


# --------------------------------------------------------------------------
# 5. ESTRATÉGIAS DE BUSCA
# --------------------------------------------------------------------------
def busca_a(consulta, base):
    """Estratégia A - palavras-chave com índice invertido.
    +1 ponto por termo da consulta presente nas palavras-chave do registro;
    +2 pontos quando uma palavra-chave inteira aparece na consulta."""
    pontos = Counter()
    for t in set(tokens(consulta)):
        for rid in base.idx_chave.get(t, ()):
            pontos[rid] += 1
    qn = " " + normalizar(consulta) + " "
    for r in base.registros:
        for kw in r["palavras_chave"]:
            if " " + normalizar(kw) + " " in qn:
                pontos[r["id"]] += 2
                break
    return sorted(((p, base.por_id[i]) for i, p in pontos.items()),
                  key=lambda x: (-x[0], x[1]["id"]))


def busca_b(consulta, base):
    """Estratégia B - TF-IDF com similaridade do cosseno sobre o texto completo do registro."""
    qc = Counter(tokens(consulta))
    qv = {t: f * base.idf[t] for t, f in qc.items() if t in base.idf}
    if not qv:
        return []
    qnorma = math.sqrt(sum(x * x for x in qv.values())) or 1.0
    res = []
    for r in base.registros:
        v = base.vet[r["id"]]
        prod = sum(w * v.get(t, 0.0) for t, w in qv.items())
        if prod > 0:
            res.append((prod / (qnorma * base.norma[r["id"]]), r))
    return sorted(res, key=lambda x: (-x[0], x[1]["id"]))


ESTRATEGIAS = {"A": (busca_a, LIMIAR_A_FRACO, LIMIAR_A_FORTE),
               "B": (busca_b, LIMIAR_B_FRACO, LIMIAR_B_FORTE)}


# --------------------------------------------------------------------------
# 6. DECISÃO DA RESPOSTA
# --------------------------------------------------------------------------
def temas_citados(consulta, base):
    """Temas cujo nome aparece na consulta (ex.: 'documentos', 'direitos')."""
    toks = set(tokens(consulta))
    achados = []
    for tid, t in base.temas.items():
        if toks & set(tokens(t["nome"])):
            achados.append(tid)
    return achados


def decidir(consulta, base, estrategia="A"):
    """Valida a consulta, busca e classifica o resultado.
    status: vazia | invalida | ok | baixa_confianca | ambigua | sem_resposta"""
    consulta = (consulta or "").strip()
    if not consulta:
        return {"status": "vazia"}
    if len(consulta) > TAMANHO_MAXIMO or not re.search(r"[A-Za-zÀ-ÿ0-9]", consulta):
        return {"status": "invalida"}
    funcao, fraco, forte = ESTRATEGIAS[estrategia]
    res = [(s, r) for s, r in funcao(consulta, base) if s >= fraco]
    if not res:
        temas = temas_citados(consulta, base)
        if temas:  # citou só o tema: pede para escolher um assunto
            opcoes = [r for t in temas for r in base.por_tema[t]]
            return {"status": "ambigua", "opcoes": opcoes[:6], "motivo": "tema"}
        return {"status": "sem_resposta"}
    if len(res) >= 2 and res[1][0] >= RAZAO_EMPATE * res[0][0]:
        return {"status": "ambigua", "opcoes": [r for _, r in res[:3]], "motivo": "empate"}
    score, melhor = res[0]
    if score < forte:
        return {"status": "baixa_confianca", "registro": melhor, "score": score}
    return {"status": "ok", "registro": melhor, "score": score,
            "alternativas": [r for _, r in res[1:3]]}


def rotulo(decisao):
    """Converte a decisão no rótulo usado nos testes."""
    return {"ok": decisao.get("registro", {}).get("id"),
            "vazia": "ENTRADA_VAZIA", "invalida": "ENTRADA_INVALIDA",
            "ambigua": "AMBIGUA", "sem_resposta": "SEM_RESPOSTA",
            "baixa_confianca": "BAIXA_CONFIANCA"}[decisao["status"]]


# --------------------------------------------------------------------------
# 7. FORMATAÇÃO DAS RESPOSTAS (MODELOS DE PROMPT)
# --------------------------------------------------------------------------
def data_br(iso):
    a, m, d = iso.split("-")
    return f"{d}/{m}/{a}"


def formatar(registro, modelo="M2", relacionados=()):
    if modelo == "M1":
        return (f"{registro['orientacao']}\n"
                f"Fonte: {registro['referencia']}")
    linhas = [
        f"ASSUNTO: {registro['pergunta']}",
        f"Tema: {registro['tema']} > {registro['subtema']}",
        "",
        f"ORIENTAÇÃO: {registro['orientacao']}",
        "",
        f"FONTE CONSULTADA: {registro['referencia']}",
        f"Última verificação na base: {data_br(registro['data_verificacao'])}",
    ]
    if registro.get("requer_confirmacao"):
        linhas.append("ATENÇÃO: confirme requisitos, valores e prazos atualizados na fonte oficial.")
    linhas.append(AVISO_NAO_OFICIAL)
    if relacionados:
        linhas += ["", "Assuntos relacionados:"]
        linhas += [f"  {i}) {r['pergunta']}" for i, r in enumerate(relacionados, 1)]
    return "\n".join(linhas)


# --------------------------------------------------------------------------
# 8. SESSÃO INTERATIVA
# --------------------------------------------------------------------------
MENU = ("\n=== CITIZEN ASSIST AI ===\n"
        "1) Escolher um tema\n"
        "2) Fazer uma pergunta\n"
        "3) Ver mapa de temas e relações\n"
        "4) Alternar modelo de resposta (atual: {modelo})\n"
        "5) Executar testes e indicadores\n"
        "0) Sair\n"
        "Digite o número da opção ou escreva sua pergunta direto.")


class Sessao:
    """Máquina de estados da conversa. entrada(texto) -> texto de saída."""

    def __init__(self, base, estrategia="A", modelo="M2"):
        self.base, self.estrategia, self.modelo = base, estrategia, modelo
        self.modo, self.opcoes, self.encerrada = "menu", [], False

    # ---- utilitários de saída ---------------------------------------------
    def menu(self):
        self.modo, self.opcoes = "menu", []
        return MENU.format(modelo=MODELOS[self.modelo]["nome"])

    def lista_temas(self):
        self.modo, self.opcoes = "escolher_tema", list(self.base.temas)
        linhas = ["Temas disponíveis:"]
        for i, tid in enumerate(self.opcoes, 1):
            t = self.base.temas[tid]
            linhas.append(f"  {i}) {t['nome']} - {t['descricao']} ({len(self.base.por_tema[tid])} orientações)")
        linhas.append("Digite o número do tema ou 'm' para o menu.")
        return "\n".join(linhas)

    def lista_registros(self, registros, titulo):
        self.modo, self.opcoes = "escolher_registro", [r["id"] for r in registros]
        linhas = [titulo]
        linhas += [f"  {i}) {r['pergunta']}" for i, r in enumerate(registros, 1)]
        linhas.append("Digite o número do assunto ou 'm' para o menu.")
        return "\n".join(linhas)

    def mapa(self):
        linhas = ["MAPA DE TEMAS (hierarquia: tema > subtema > orientação)"]
        for tid, t in self.base.temas.items():
            linhas.append(f"\n{t['nome']}")
            for sid, snome in t["subtemas"].items():
                regs = self.base.por_subtema.get((tid, sid), [])
                if regs:
                    linhas.append(f"  - {snome}: " + ", ".join(r["id"] for r in regs))
        linhas.append("\nRelações (grafo): cada orientação se liga às relacionadas (peso 1), "
                      "às do mesmo subtema (peso 2) e do mesmo tema (peso 3); "
                      "as sugestões usam o algoritmo de Dijkstra.")
        return "\n".join(linhas)

    def mostrar(self, rid):
        r = self.base.por_id[rid]
        rel = self.base.relacionados(rid, 3)
        self.modo, self.opcoes = "pos_resposta", [x["id"] for x in rel]
        texto = formatar(r, self.modelo, rel if self.modelo == "M2" else ())
        if self.modelo == "M1":
            texto += "\n\nAssuntos relacionados:\n" + "\n".join(
                f"  {i}) {x['pergunta']}" for i, x in enumerate(rel, 1))
        return (texto + "\n\nDigite 1-3 para continuar, 'p' para nova pergunta ou 'm' para o menu.")

    def sem_resposta(self, motivo):
        return (f"{motivo}\n"
                "Não encontrei orientação confiável na base para isso e prefiro não inventar "
                "instruções. Para informações oficiais, consulte o site do órgão responsável "
                "(por exemplo, gov.br).\n" + AVISO_NAO_OFICIAL +
                "\nSe for uma emergência: ligue 192 (SAMU); para apoio emocional, CVV pelo 188.\n"
                "\nVocê pode tentar:\n"
                "  - reformular a pergunta com outras palavras;\n  - escolher um tema:\n"
                + self.lista_temas())

    # ---- fluxo de consulta ---------------------------------------------------
    def responder(self, consulta):
        d = decidir(consulta, self.base, self.estrategia)
        st = d["status"]
        if st == "vazia":
            self.modo = "aguardando_pergunta"
            return "Você não digitou nada. Escreva sua pergunta (ex.: Como consultar o CPF?) ou 'm' para o menu."
        if st == "invalida":
            self.modo = "aguardando_pergunta"
            return ("Não consegui entender essa entrada. Use palavras (até 300 caracteres), "
                    "por exemplo: Como pedir seguro-desemprego?")
        if st == "sem_resposta":
            return self.sem_resposta("Sua pergunta ficou fora dos assuntos da base.")
        if st == "ambigua":
            txt = ("Sua consulta pode se referir a mais de um assunto. "
                   if d["motivo"] == "empate" else "Você citou apenas o tema. ")
            return txt + "\n" + self.lista_registros(d["opcoes"], "Qual destes você quer ver?")
        if st == "baixa_confianca":
            self.modo, self.opcoes = "confirmar", [d["registro"]["id"]]
            return (f"Encontrei uma correspondência fraca. Você quis dizer: "
                    f"\"{d['registro']['pergunta']}\"? (s/n)")
        return self.mostrar(d["registro"]["id"])

    def entrada(self, texto):
        t = (texto or "").strip()
        tl = t.lower()
        if tl in ("m", "menu") and self.modo != "menu":
            return self.menu()
        if self.modo == "menu":
            if not t:
                return "Você não digitou nada. Escolha uma opção (0-5) ou escreva sua pergunta."
            if t.isdigit():
                return self._opcao_menu(int(t))
            return self.responder(t)
        if self.modo == "aguardando_pergunta":
            return self.responder(t)
        if self.modo == "escolher_tema":
            if t.isdigit() and 1 <= int(t) <= len(self.opcoes):
                tid = self.opcoes[int(t) - 1]
                return self.lista_registros(self.base.por_tema[tid],
                                            f"Orientações em {self.base.temas[tid]['nome']}:")
            return "Opção inexistente. Digite um número da lista ou 'm' para o menu."
        if self.modo == "escolher_registro":
            if t.isdigit() and 1 <= int(t) <= len(self.opcoes):
                return self.mostrar(self.opcoes[int(t) - 1])
            if t and not t.isdigit():
                return self.responder(t)
            return "Opção inexistente. Digite um número da lista ou 'm' para o menu."
        if self.modo == "pos_resposta":
            if t.isdigit():
                if 1 <= int(t) <= len(self.opcoes):
                    return self.mostrar(self.opcoes[int(t) - 1])
                return "Opção inexistente. Digite 1-3, 'p' ou 'm'."
            if tl == "p":
                self.modo = "aguardando_pergunta"
                return "Escreva sua nova pergunta:"
            if not t:
                return "Você não digitou nada. Digite 1-3, 'p' ou 'm'."
            return self.responder(t)
        if self.modo == "confirmar":
            if tl in ("s", "sim"):
                return self.mostrar(self.opcoes[0])
            if tl in ("n", "nao", "não"):
                return self.sem_resposta("Certo, não é esse assunto.")
            return "Responda 's' para sim ou 'n' para não."
        return self.menu()

    def _opcao_menu(self, n):
        if n == 0:
            self.encerrada = True
            return "Até logo! Lembre-se: confirme sempre as informações nas fontes oficiais."
        if n == 1:
            return self.lista_temas()
        if n == 2:
            self.modo = "aguardando_pergunta"
            return "Escreva sua pergunta:"
        if n == 3:
            return self.mapa()
        if n == 4:
            self.modelo = "M1" if self.modelo == "M2" else "M2"
            return f"Modelo de resposta alterado para: {MODELOS[self.modelo]['nome']}"
        if n == 5:
            return executar_tudo(self.base, silencioso=False)
        return "Opção inexistente. Escolha um número de 0 a 5."


# --------------------------------------------------------------------------
# 9. TESTES, INDICADORES E USABILIDADE
# --------------------------------------------------------------------------
def carregar_testes(caminho=CAMINHO_TESTES):
    if not os.path.exists(caminho):
        raise ErroBase(f"Arquivo de testes não encontrado: {caminho}")
    with open(caminho, encoding="utf-8") as f:
        return json.load(f)


def medir_ms(base, entrada, estrategia, repeticoes=200):
    """Tempo médio de consulta em milissegundos (média de várias repetições)."""
    ini = time.perf_counter()
    for _ in range(repeticoes):
        decidir(entrada, base, estrategia)
    return (time.perf_counter() - ini) / repeticoes * 1000


def rodar_testes(base, estrategia):
    resultados = []
    for caso in carregar_testes():
        d = decidir(caso["entrada"], base, estrategia)
        obtido = rotulo(d)
        resultados.append({
            "id": caso["id"], "tipo": caso["tipo"], "entrada": caso["entrada"],
            "esperado": caso["esperado"], "obtido": obtido,
            "acerto": obtido == caso["esperado"],
            "tempo_ms": round(medir_ms(base, caso["entrada"], estrategia), 4)})
    return resultados


def resumo(resultados):
    n = len(resultados)
    acertos = sum(r["acerto"] for r in resultados)
    return {"total": n, "acertos": acertos,
            "taxa_acerto": round(acertos / n * 100, 1),
            "tempo_medio_ms": round(sum(r["tempo_ms"] for r in resultados) / n, 4)}


def pontuar_formato(registro, texto):
    """Checklist (0-5) de qualidade do formato de resposta."""
    criterios = {
        "cita_fonte": registro["referencia"] in texto,
        "cita_data": data_br(registro["data_verificacao"]) in texto,
        "aviso_nao_oficial": "NÃO é um canal oficial" in texto,
        "aviso_confirmacao": (not registro.get("requer_confirmacao")) or "confirme" in texto.lower(),
        "proximos_passos": "relacionados" in texto.lower(),
    }
    return sum(criterios.values()), criterios


def comparar_modelos(base, resultados):
    saida = {}
    corretos = [r for r in resultados if r["acerto"] and r["esperado"] in base.por_id]
    for m in MODELOS:
        pts, tam = [], []
        for r in corretos:
            reg = base.por_id[r["esperado"]]
            rel = base.relacionados(reg["id"], 3)
            texto = formatar(reg, m, rel if m == "M2" else ())
            if m == "M1":  # M1 também oferece os relacionados no fluxo da sessão
                texto += "\nAssuntos relacionados:"
            pts.append(pontuar_formato(reg, texto)[0])
            tam.append(len(texto))
        saida[m] = {"pontuacao_media": round(sum(pts) / len(pts), 2),
                    "tamanho_medio_caracteres": round(sum(tam) / len(tam)),
                    "respostas_avaliadas": len(pts)}
    return saida


def roteiro_usabilidade(base):
    """Roteiro de tarefas executado automaticamente: conta passos e confere o resultado."""
    tarefas = [
        ("T1 Perguntar sobre o CPF", ["2", "Como consultar a situação do meu CPF?"], "receita federal"),
        ("T2 Navegar por menu até uma orientação", ["1", "1", "1"], "fonte consultada"),
        ("T3 Seguir um assunto relacionado", ["1", "1", "1", "1"], "assunto:"),
        ("T4 Recuperar-se de opção inválida e entrada vazia", ["9", "", "2", "Como pedir seguro-desemprego?"], "seguro-desemprego"),
        ("T5 Pergunta fora da base e alternativas", ["2", "Como fazer bolo de chocolate?"], "temas disponíveis"),
    ]
    saida = []
    for nome, passos, esperado in tarefas:
        s = Sessao(base)
        textos = [s.entrada(p) for p in passos]
        final = textos[-1].lower()
        ok = esperado in final
        if nome.startswith("T4"):  # também exige mensagens compreensíveis nos erros
            ok = ok and "inexistente" in textos[0].lower() and "não digitou" in textos[1].lower()
        saida.append({"tarefa": nome, "passos": len(passos), "concluida": ok})
    return saida


def executar_tudo(base, silencioso=False):
    ind = {}
    linhas = []
    for est in ESTRATEGIAS:
        res = rodar_testes(base, est)
        ind[est] = {"resumo": resumo(res), "resultados": res}
    principal = ind["A"]["resultados"]
    ind["modelos"] = comparar_modelos(base, principal)
    ind["usabilidade"] = roteiro_usabilidade(base)
    with open(CAMINHO_RESULTADOS, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["id", "tipo", "entrada", "esperado", "obtido_A", "acerto_A", "tempo_ms_A",
                    "obtido_B", "acerto_B", "tempo_ms_B"])
        for a, b in zip(ind["A"]["resultados"], ind["B"]["resultados"]):
            w.writerow([a["id"], a["tipo"], a["entrada"], a["esperado"], a["obtido"],
                        "ACERTO" if a["acerto"] else "ERRO", a["tempo_ms"],
                        b["obtido"], "ACERTO" if b["acerto"] else "ERRO", b["tempo_ms"]])
    with open(CAMINHO_INDICADORES, "w", encoding="utf-8") as f:
        json.dump(ind, f, ensure_ascii=False, indent=2)
    for est in ESTRATEGIAS:
        r = ind[est]["resumo"]
        linhas.append(f"Estratégia {est}: {r['acertos']}/{r['total']} corretas "
                      f"(taxa de acerto {r['taxa_acerto']}%), tempo médio {r['tempo_medio_ms']} ms")
    for m, v in ind["modelos"].items():
        linhas.append(f"Modelo {m}: checklist {v['pontuacao_media']}/5, "
                      f"tamanho médio {v['tamanho_medio_caracteres']} caracteres")
    conc = sum(t["concluida"] for t in ind["usabilidade"])
    passos = sum(t["passos"] for t in ind["usabilidade"]) / len(ind["usabilidade"])
    linhas.append(f"Roteiro de usabilidade: {conc}/{len(ind['usabilidade'])} tarefas concluídas, "
                  f"média de {passos:.1f} entradas por tarefa")
    linhas.append(f"Resultados detalhados salvos em: {CAMINHO_RESULTADOS}")
    return "\n".join(linhas)


# --------------------------------------------------------------------------
# PROGRAMA PRINCIPAL
# --------------------------------------------------------------------------
def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    try:
        base, descartados = construir_base()
    except ErroBase as e:
        print(f"Não foi possível iniciar: {e}")
        return 1
    if "--testes" in sys.argv:
        print(executar_tudo(base))
        return 0
    print(AVISO_NAO_OFICIAL)
    if descartados:
        print(f"Atenção: {len(descartados)} registro(s) inválido(s) foram ignorados:")
        for rid, probs in descartados:
            print(f"  - {rid}: {'; '.join(probs)}")
    print(f"Base carregada: {len(base.registros)} orientações em {len(base.temas)} temas.")
    sessao = Sessao(base)
    print(sessao.menu())
    while not sessao.encerrada:
        try:
            texto = input("\n> ")
        except (EOFError, KeyboardInterrupt):
            print("\nEncerrando.")
            break
        print("\n" + sessao.entrada(texto))
    return 0


if __name__ == "__main__":
    sys.exit(main())
