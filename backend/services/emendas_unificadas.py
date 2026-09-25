"""A emenda federal UMA VEZ SÓ, venha ela de onde vier — lógica pura, sem banco.

A mesma emenda aparece em até quatro tabelas do PACTHA, cada uma com um pedaço:

    emendas_federais_carteira .. a indicação (dump) + execução CGU. É a BASE.
    transferegov_te ............ o Plano de Ação da emenda Pix (OB, conta, extrato).
    parcerias_propostas ........ a proposta de saúde do módulo Parcerias.
    parcerias_emendas_indicadas  a indicação de saúde que ainda não virou proposta.
    transferegov_propostas ..... o convênio voluntário que a emenda financia.
    convenios_estadual (FNS) ... a proposta de saúde fundo a fundo (2014 em diante).

⚠️⚠️ A CHAVE É O CÓDIGO DE 12 DÍGITOS (ano 4 + autor 4 + sequência 4), e cada
fonte escreve de um jeito: a carteira grava `202432980001`, a TE
`202432980001-Heitor Schuch`, Parcerias `2024.3298.0001`. `codigo_de` reduz os
três ao mesmo texto. As voluntárias não trazem o código: casam pelo
`id_proposta` que a própria carteira lista.

⚠️ O QUE CASA VIRA INSTRUMENTO DA LINHA, E NÃO SOMA. Somar o valor do plano ao
valor indicado da mesma emenda é contar o mesmo dinheiro duas vezes. O que NÃO
casa vira linha própria — perder a emenda Pix porque a carteira não a viu seria
o erro oposto, e o mais caro dos dois (é o que o gestor procura).

⚠️ O PAC FICA FORA DESTA LISTA, de propósito: não traz código de emenda — só
o NOME do parlamentar —, e casar por nome apagaria emenda legítima (a regra já
escrita em `routers/parlamentares.py`, bloco 7). Continua na aba Parlamentares.

⭐ O FNS ENTRA PELO CÓDIGO (medido em 25/09/2026). `nuAnoExercicio` +
`coEmendaPolitica` (sempre 8 dígitos) em `linhaPropostas[].parlamentares[]` É o
código de 12 dígitos da CGU: 36 de 38 pares em Nova Palma e 54 de 58 em Monte
Sião acharam a emenda na planilha da CGU com o MESMO autor. Até aqui as emendas
de saúde de 2014-2024 não apareciam nesta aba — nem a carteira (o dump casa pelo
CNPJ da prefeitura, não o do Fundo) nem o Parcerias (só 2025+) as viam: 23 em
Nova Palma e 40 em Monte Sião passam a aparecer. Ver `emendas_fns`.
"""
from __future__ import annotations

import json
import re
import unicodedata
from typing import Optional

from services.nome_parlamentar import e_parlamentar_real, e_pessoa

COLEGIADOS = ("BANCADA", "COMISSAO", "RELATOR GERAL")

# Os grupos de `routers/emendas_federais.classificar` que dizem se houve pagamento.
GRUPOS_COM_EXECUCAO = ("sem_empenho", "parado", "andamento", "paga")

# Rótulo curto do instrumento, o que a tela escreve no selo.
ROTULO_ORIGEM = {
    "federal": "Emenda federal",
    "te": "Transferência especial (Pix)",
    "parcerias": "Saúde (Parcerias)",
    "indicacao": "Saúde — indicada",
    "voluntaria": "Voluntária (convênio)",
    "fns": "Saúde (FNS)",
}


def codigo_de(texto) -> Optional[str]:
    """Os 12 dígitos da emenda, ou None. Só a parte ANTES do primeiro '-' conta:
    depois dele vem o nome do autor, e "Deputado 2º" não pode virar dígito."""
    if texto is None:
        return None
    base = str(texto).split("-", 1)[0]
    dig = re.sub(r"\D", "", base)
    return dig if len(dig) == 12 else None


def _norm(s) -> str:
    s = "".join(c for c in unicodedata.normalize("NFKD", str(s or ""))
                if not unicodedata.combining(c))
    return " ".join(s.upper().split())


def autores_de(texto) -> list[str]:
    """A voluntária pode trazer "FULANO, BELTRANO": um autor por nome."""
    return [p.strip() for p in str(texto or "").split(",") if len(p.strip()) >= 3]


def _ano(v) -> Optional[int]:
    try:
        return int(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _linha(origem: str, ident, **campos) -> dict:
    base = {
        "chave": f"{origem}:{ident}", "origem": origem, "id": str(ident),
        "origem_rotulo": ROTULO_ORIGEM[origem],
        "codigo_emenda": None, "ano": None, "autor": None, "tipo": None,
        "impositiva": None, "objeto": None, "situacao": None,
        "valor": None, "municipal": True,
        "grupo": None, "motivo": None, "execucao": None,
        "instrumentos": [],
    }
    base.update(campos)
    return base


def _instrumento(origem: str, ident, situacao=None, valor=None, objeto=None) -> dict:
    return {"origem": origem, "id": str(ident), "rotulo": ROTULO_ORIGEM[origem],
            "situacao": situacao, "valor": valor, "objeto": objeto}


def _tipo_fns(recurso) -> Optional[str]:
    """`dsTipoRecurso` ("EMENDA INDIVIDUAL", "EMENDA DE BANCADA"...) no tipo da CGU."""
    r = _norm(recurso)
    for trecho, tipo in (("INDIVID", "INDIVIDUAL"), ("BANCADA", "BANCADA"),
                         ("COMISS", "COMISSAO"), ("RELATOR", "RELATOR GERAL")):
        if trecho in r:
            return tipo
    return None


def _dinheiro(v) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def emendas_fns(grupos: list[dict]) -> list[dict]:
    """As emendas das propostas de saúde do FNS, UMA por (proposta, código).

    `grupos` são as linhas FNS de `convenios_estadual`: `objeto` (o tipo da
    proposta, "INCREMENTO MAC"), `recurso` (`dsTipoRecurso`) e `props`
    (`raw_data.linhaPropostas`). As armadilhas medidas em 25/09/2026:

    1. ⚠️ A MESMA PROPOSTA VEM EM MAIS DE UM GRUPO: o coletor busca as propostas
       individuais por (ano, tipo, recurso), e o grupo é por nº de processo —
       dois processos do mesmo tipo repetem a lista. Deduplica por
       (nº da proposta, código).
    2. Uma proposta pode ter VÁRIOS autores (2 em Nova Palma, 6 em Monte Sião):
       um item por código, cada um com o SEU `vlIndObjeto`.
    3. O mesmo código em MAIS DE UMA proposta: fica para `unificar_federais`
       agrupar (a emenda soma as partes, cada proposta é um instrumento).
    4. ⚠️ O "RECEBIDO" É O `vlPago` DO FNS, não o da CGU: na planilha de
       favorecidos da CGU o pagamento FNS de 2024 sai para o BANCO DO BRASIL,
       não para o fundo. Numa proposta com várias emendas, o pago é dividido
       pela parte de cada uma.
    5. O nome vem com acento no FNS ("JÚLIO DELGADO") e sem na CGU: quem casa é
       o código, nunca o nome.
    """
    vistos: set[tuple[str, str]] = set()
    out: list[dict] = []
    for g in grupos:
        props = g.get("props")
        if isinstance(props, str):
            try:
                props = json.loads(props)
            except (ValueError, TypeError):
                props = None
        if not isinstance(props, list):
            continue
        for prop in props:
            if not isinstance(prop, dict):
                continue
            numero = str(prop.get("nuProposta") or "").strip()
            por_codigo: dict[str, dict] = {}
            for pp in prop.get("parlamentares") or ():
                if not isinstance(pp, dict):
                    continue
                co = re.sub(r"\D", "", str(pp.get("coEmendaPolitica") or ""))
                ano = re.sub(r"\D", "", str(pp.get("nuAnoExercicio") or ""))
                cod = codigo_de(f"{ano}{co.zfill(8)}") if co and len(ano) == 4 else None
                if not cod:
                    continue
                nome = (pp.get("noApelidoPolitico") or pp.get("noParlamentar")
                        or pp.get("nome") or "").strip()
                item = por_codigo.setdefault(cod, {"autor": None, "valor": 0.0})
                if nome and not item["autor"] and e_parlamentar_real(nome):
                    item["autor"] = nome
                item["valor"] += _dinheiro(pp.get("vlIndObjeto"))
            if not por_codigo:
                continue
            vl_prop = _dinheiro(prop.get("vlProposta"))
            vl_pago = prop.get("vlPago")
            for cod, item in por_codigo.items():
                if (numero, cod) in vistos:
                    continue
                vistos.add((numero, cod))
                # Sem `vlIndObjeto` e com uma emenda só, a proposta inteira é dela.
                parte = item["valor"] or (vl_prop if len(por_codigo) == 1 else 0.0)
                if vl_prop and parte > vl_prop:
                    parte = vl_prop
                pago = None
                if vl_pago is not None:
                    pago = _dinheiro(vl_pago) * (parte / vl_prop if vl_prop else 1.0)
                out.append({
                    "codigo": cod, "autor": item["autor"], "valor": round(parte, 2),
                    "numero": numero or None,
                    "situacao": str(prop.get("situacao_desc") or "").strip() or None,
                    "valor_proposta": vl_prop,
                    "pago": round(pago, 2) if pago is not None else None,
                    "data_pagamento": str(prop.get("data_pagamento") or "").strip() or None,
                    "objeto": str(g.get("objeto") or "").strip() or None,
                    "tipo": _tipo_fns(g.get("recurso")),
                })
    return out


def unificar_federais(carteira: list[dict], te: list[dict], parcerias: list[dict],
                      indicadas: list[dict], voluntarias: list[dict],
                      fns: Optional[list[dict]] = None) -> list[dict]:
    """Uma linha por emenda. Cada lista chega no formato das consultas do router
    (ver `routers/emendas_parlamentares.py`), já filtrada pelo município."""
    linhas: list[dict] = []
    por_codigo: dict[str, dict] = {}
    por_proposta: dict[str, list[dict]] = {}

    # 1) A carteira é a base: é a única que tem a execução CGU e o impositivo.
    for e in carteira:
        cod = codigo_de(e.get("codigo_emenda"))
        ident = cod or f"sem-codigo-{len(linhas)}"
        execucao = None
        if e.get("execucao_consultada"):
            execucao = {k: e.get(k) for k in (
                "valor_empenhado", "valor_liquidado", "valor_pago",
                "valor_resto_inscrito", "valor_resto_cancelado", "valor_resto_pago")}
        ln = _linha("federal", ident, codigo_emenda=cod, ano=_ano(e.get("ano")),
                    autor=e.get("autor"), tipo=e.get("tipo"),
                    impositiva=e.get("impositiva"), valor=e.get("valor_indicado"),
                    municipal=bool(e.get("beneficiario_prefeitura")),
                    beneficiario=e.get("beneficiario_nome"),
                    orgao=e.get("orgao"), grupo=e.get("grupo"),
                    motivo=e.get("motivo"), execucao=execucao,
                    execucao_consultada=bool(e.get("execucao_consultada")),
                    documentos_n=e.get("documentos_n") or 0,
                    url_fonte=e.get("url_fonte"),
                    # Pago a quem está NESTE município (planilha de favorecidos da
                    # CGU) — POR CÓDIGO, não por beneficiário da carteira.
                    recebido_municipio=e.get("recebido_municipio"),
                    convenios_n=e.get("convenios_n") or 0)
        # ⚠️ O mesmo código pode vir em DUAS linhas da carteira (dois beneficiários
        # no município: a prefeitura e o hospital). O `id` continua o código — o
        # detalhe mostra as duas —, mas a `chave` da lista não pode repetir.
        if cod and cod in por_codigo:
            ln["chave"] = f"federal:{cod}:{len(linhas)}"
        linhas.append(ln)
        if cod:
            por_codigo.setdefault(cod, ln)
        for p in e.get("propostas") or ():
            por_proposta.setdefault(str(p), []).append(ln)

    def _anexa_ou_cria(cod, instrumento, criar):
        alvo = por_codigo.get(cod) if cod else None
        if alvo is not None:
            alvo["instrumentos"].append(instrumento)
            return
        ln = criar()
        linhas.append(ln)
        if cod:
            por_codigo[cod] = ln

    # 2) Transferência especial — o plano de ação da emenda Pix.
    for t in te:
        cod = codigo_de(t.get("emenda"))
        _anexa_ou_cria(
            cod,
            _instrumento("te", t["plano_acao_id"], t.get("situacao"),
                         t.get("valor_total"), t.get("objeto")),
            lambda t=t, cod=cod: _linha(
                "te", t["plano_acao_id"], codigo_emenda=cod,
                ano=_ano(cod[:4]) if cod else None, autor=t.get("parlamentar"),
                tipo="INDIVIDUAL", impositiva=True, objeto=t.get("objeto"),
                situacao=t.get("situacao"), valor=t.get("valor_total")))

    # 3) Parcerias — a proposta de saúde.
    com_proposta: set[str] = set()
    for p in parcerias:
        cod = codigo_de(p.get("numero_emenda"))
        if cod:
            com_proposta.add(cod)
        valor = p.get("valor_emenda") if p.get("valor_emenda") is not None else p.get("valor_total")
        _anexa_ou_cria(
            cod,
            _instrumento("parcerias", p["id_proposta"], p.get("situacao"), valor,
                         p.get("objeto")),
            lambda p=p, cod=cod, valor=valor: _linha(
                "parcerias", p["id_proposta"], codigo_emenda=cod,
                ano=_ano(p.get("ano")) or (_ano(cod[:4]) if cod else None),
                autor=p.get("parlamentar"), tipo=p.get("tipo_emenda"),
                objeto=p.get("objeto"), situacao=p.get("situacao"), valor=valor,
                municipal=p.get("municipal", True)))

    # 4) Indicação de saúde SEM proposta — a proposta, quando existe, já entrou.
    for i in indicadas:
        cod = codigo_de(i.get("numero_emenda"))
        if not cod or cod in com_proposta:
            continue
        _anexa_ou_cria(
            cod,
            _instrumento("indicacao", cod, "Indicada, sem proposta", i.get("valor_total")),
            lambda i=i, cod=cod: _linha(
                "indicacao", cod, codigo_emenda=cod,
                ano=_ano(i.get("ano")) or _ano(cod[:4]), autor=i.get("parlamentar"),
                tipo=i.get("tipo"), situacao="Indicada, sem proposta",
                valor=i.get("valor_total"), municipal=i.get("municipal", True)))

    # 5) FNS — a proposta de saúde fundo a fundo, pelo código (`emendas_fns`).
    # O que casa com a carteira, a TE ou o Parcerias vira instrumento e NÃO soma;
    # o resto vira uma linha por código, com a soma das partes das propostas.
    fns_por_codigo: dict[str, list[dict]] = {}
    for f in fns or ():
        fns_por_codigo.setdefault(f["codigo"], []).append(f)
    for cod, props in fns_por_codigo.items():
        insts = [_instrumento("fns", p["numero"] or cod, p.get("situacao"), p.get("valor"),
                              p.get("objeto")) for p in props]
        alvo = por_codigo.get(cod)
        if alvo is not None:
            alvo["instrumentos"].extend(insts)
            continue
        pagos = [p["pago"] for p in props if p.get("pago") is not None]
        situacoes = list(dict.fromkeys(p["situacao"] for p in props if p.get("situacao")))
        objetos = list(dict.fromkeys(p["objeto"] for p in props if p.get("objeto")))
        ln = _linha("fns", cod, codigo_emenda=cod, ano=_ano(cod[:4]),
                    autor=next((p["autor"] for p in props if p.get("autor")), None),
                    tipo=next((p["tipo"] for p in props if p.get("tipo")), None),
                    objeto=" · ".join(objetos) or None,
                    situacao=" · ".join(situacoes) or None,
                    valor=round(sum(p.get("valor") or 0.0 for p in props), 2),
                    recebido_municipio=round(sum(pagos), 2) if pagos else None,
                    instrumentos=insts)
        linhas.append(ln)
        por_codigo[cod] = ln

    # 6) Voluntárias — casam pelo id da proposta que a carteira lista.
    for v in voluntarias:
        inst = _instrumento("voluntaria", v["numero_proposta"], v.get("situacao"),
                            v.get("valor_emenda"), v.get("objeto"))
        alvos = por_proposta.get(str(v.get("id_proposta_siconv") or ""), [])
        if alvos:
            for a in alvos:
                a["instrumentos"].append(inst)
            continue
        ano = str(v.get("numero_proposta") or "").rpartition("/")[2]
        linhas.append(_linha(
            "voluntaria", v["numero_proposta"], ano=_ano(ano),
            autor=v.get("parlamentar"), objeto=v.get("objeto"),
            situacao=v.get("situacao"),
            valor=v.get("valor_emenda") if v.get("valor_emenda") is not None
            else v.get("valor_repasse"),
            municipal=v.get("municipal", True)))

    for ln in linhas:
        tipo = _norm(ln.get("tipo"))
        ln["autores"] = autores_de(ln.get("autor"))
        # ⚠️ O TIPO NÃO BASTA. A voluntária e a TE não trazem `tipo`, e o autor
        # delas vem como "BANCADA DE MINAS GERAIS" ou "COM. CULTURA" — medido na
        # Freitas em 17/09/2026, eram os 5 "sem partido" que não eram gente.
        ln["colegiado"] = tipo in COLEGIADOS or bool(
            ln["autores"] and not any(e_pessoa(a) for a in ln["autores"]))
        # O que a tela desenha como selo: a origem da linha e a de cada instrumento.
        ln["origens"] = sorted({ln["origem"], *(i["origem"] for i in ln["instrumentos"])})
    linhas.sort(key=lambda l: (-(l["ano"] or 0), -(l["valor"] or 0)))
    return linhas


def filtrar(linhas: list[dict], anos=None, autor=None, tipo=None, origem=None) -> list[dict]:
    """Os filtros da aba. ⚠️ Os totais saem DEPOIS disto, da lista filtrada: cartão
    que soma a base inteira embaixo de uma lista filtrada se contradiz na tela."""
    anos = {int(a) for a in anos or ()}
    alvo = _norm(autor) if autor else ""
    tipo_n = _norm(tipo) if tipo else ""
    out = []
    for l in linhas:
        if anos and l["ano"] not in anos:
            continue
        if alvo and alvo not in _norm(l.get("autor")):
            continue
        if tipo_n and _norm(l.get("tipo")) != tipo_n:
            continue
        if origem and origem not in l["origens"]:
            continue
        out.append(l)
    return out


def totais(linhas: list[dict]) -> dict:
    """⚠️ SÓ `valor` SOMA, e só o da prefeitura. A execução CGU é da emenda INTEIRA,
    nacional — somá-la deu R$ 4 bilhões em Nova Palma (ver `routers/
    emendas_federais.py`). Aqui ela só conta ESTADO: quantas andaram, quantas
    pararam."""
    t = {"emendas": len(linhas), "valor_prefeitura": 0.0, "fora_prefeitura_n": 0,
         "fora_prefeitura_valor": 0.0, "parado_n": 0, "com_pagamento_n": 0,
         "nao_consultadas_n": 0, "com_execucao_n": 0, "impositivas_n": 0, "por_origem": {},
         # ⭐ O único valor de EXECUÇÃO que soma: o pago a quem está neste
         # município (favorecidos da CGU). ⚠️ UMA VEZ POR CÓDIGO — a mesma emenda
         # pode ter duas linhas (prefeitura e hospital), e o recebido é do código.
         "recebido_municipio": 0.0}
    codigos_somados: set = set()
    for l in linhas:
        cod = l.get("codigo_emenda")
        if l.get("recebido_municipio") and cod and cod not in codigos_somados:
            codigos_somados.add(cod)
            t["recebido_municipio"] += l["recebido_municipio"]
        v = l["valor"] or 0.0
        if l["municipal"]:
            t["valor_prefeitura"] += v
        else:
            t["fora_prefeitura_n"] += 1
            t["fora_prefeitura_valor"] += v
        if l["grupo"] == "parado":
            t["parado_n"] += 1
        # ⚠️ O DENOMINADOR DO "SEM PAGAMENTO". Só a emenda da carteira com execução
        # no Portal tem `grupo` que mede pagamento; Pix, Saúde e voluntária não
        # têm. Medido na Freitas (2026, 19/09): 33 de 354 linhas — "0 sem
        # pagamento" sem dizer "de 33" é lido como "todas as 354 pagas".
        if l["grupo"] in GRUPOS_COM_EXECUCAO:
            t["com_execucao_n"] += 1
        # ⚠️ A linha SEM Nº DA EMENDA fica fora (24/09/2026): não há consulta
        # possível, e o cartão dizia "1 da carteira ainda não consultada(s)"
        # para sempre. Ela tem grupo e motivo próprios (`sem_codigo`).
        if (l["origem"] == "federal" and not l.get("execucao_consultada")
                and l.get("grupo") != "sem_codigo"):
            t["nao_consultadas_n"] += 1
        ex = l["execucao"] or {}
        if (ex.get("valor_pago") or 0) + (ex.get("valor_resto_pago") or 0) > 0:
            t["com_pagamento_n"] += 1
        if l["impositiva"]:
            t["impositivas_n"] += 1
        for o in l["origens"]:
            t["por_origem"][o] = t["por_origem"].get(o, 0) + 1
    t["valor_prefeitura"] = round(t["valor_prefeitura"], 2)
    t["fora_prefeitura_valor"] = round(t["fora_prefeitura_valor"], 2)
    t["recebido_municipio"] = round(t["recebido_municipio"], 2)
    return t
