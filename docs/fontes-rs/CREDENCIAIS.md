# Credenciais — o que cada uma destrava, e quem a tem

> **Nada aqui foi pedido a ninguém.** A decisão registrada é não solicitar
> credencial à prefeitura enquanto ela avalia o sistema. Este documento existe
> para que a decisão de pedir — quando vier — seja tomada sabendo exatamente o
> que se ganha e o que se assume.
>
> Cada linha diz: o que já coletamos **sem** a credencial, o que ela acrescenta,
> quem costuma tê-la, e o que já está pronto no código esperando por ela.

---

## 1. Portal da Transparência federal (CGU) — chave de API

| | |
|---|---|
| **Como obter** | `portaldatransparencia.gov.br/api-de-dados/cadastrar-email`, com conta gov.br **Prata ou Ouro** |
| **Quem tem** | Qualquer pessoa física com conta gov.br verificada — **inclusive você** |
| **Env** | `PORTAL_TRANSPARENCIA_API_KEY` |
| **Coletor** | ✅ `backend/ingestion/portal_transparencia.py` — **no ar desde 06/09/2026** |

**⚠️ O passivo, que é o motivo de isto não ser trivial.** A chave fica vinculada
ao **CPF de quem a cadastrou**. Num produto com cinco tenants, a chave de uma
pessoa passa a responder pelas consultas de todas as prefeituras. Não é
impedimento — é uma escolha consciente, e a decisão de 06/09/2026 foi ligá-la
**só em `novapalma-rs` e `montesiao-mg`**. A chave não é pedida ao cliente.

**O que ela NÃO acrescenta.** O endpoint `/convenios` é derivado do SICONV com
menos colunas do que o dump do TransfereGov que já coletamos, e o `ConvenioDTO`
**não tem campo de emenda** (conferido no Swagger em 06/09/2026 — o vínculo que a
CGU anunciou em nov/2024 está na *tela* do portal, não na API). A auditoria de
29/08/2026 estava certa nisso.

**⭐ O QUE MUDOU A CONTA EM 06/09/2026, e não estava neste documento.** O valor
principal não vem da chave: vem do **dump aberto `siconv_emenda.zip`**, que tem
`BENEFICIARIO_EMENDA` = **CNPJ de 14 dígitos** em 298.107 das 298.114 linhas.
Casando com o CNPJ que o `siconfi.py` já grava em `municipios.cnpj` (conferido:
bate exatamente), sai a **carteira inteira de emendas federais do município** —
sem chave nenhuma, nos cinco tenants:

| | Emendas | Valor | Período | Parlamentares |
|---|---|---|---|---|
| Nova Palma/RS (`88488358000156`) | 44 | R$ 13,68 mi | 2009–2026 | 17 |
| Monte Sião/MG (`22646525000131`) | 33 | R$ 12,24 mi | 2009–2026 | 18 |

⚠️ **Esses números contam a prefeitura E as entidades do município.** A carga real de
06/09 trouxe só as da prefeitura (Nova Palma: 37 códigos, R$ 12,28 mi), porque o CNPJ do
Hospital N. S. da Piedade não estava cadastrado. É o que a tabela `municipio_entidades`
resolve — cadastro explícito, com `origem`, e nunca casamento por nome.

E o número que justificou o trabalho: **45% dessas emendas têm `ID_PROPOSTA`
vazio**. Todo caminho que o produto usava para chegar em emenda federal passava
por proposta — quase metade da carteira era invisível.

**O que a CHAVE acrescenta em cima disso:**

1. **`/emendas?codigoEmenda=`** — empenhado, liquidado, pago e restos.
   ⚠️ **O agregado é NACIONAL**, da emenda inteira e não da fatia do município:
   é por isso que `emendas_federais_cgu` não tem `municipio_id`.
2. **`/emendas/documentos/{codigo}`** — a linha do tempo da execução
   (empenho → liquidação → pagamento). Sem valor: o DTO não traz.
3. **Programas sociais por município** — `novo-bolsa-familia-por-municipio`,
   `bpc-por-municipio`, `auxilio-brasil`, `seguro-defeso`, `safra`, `peti`, por
   `codigoIbge` + `mesAno`. **Fora da primeira leva por decisão** (06/09/2026):
   são 360 requisições por município, e num tenant de 41 isso é território de
   suspensão do token.

**⚠️ E o que ela não tem:** filtro territorial em `/emendas`. Os parâmetros são
`codigoEmenda`, `numeroEmenda`, `nomeAutor`, `tipoEmenda`, `ano`, `codigoFuncao`
— nenhum de município. O território vem do dump, por CNPJ; a chave só responde
sobre códigos que já temos.

**⚠️ Cotas:** 700 req/min das 00:00 às 05:59, 400 nas demais horas, **180 nas
APIs restritas**, e estourar **suspende o token por 8h**. `/emendas` não está na
lista de restritas. A rodada dos dois municípios custa ~154 requisições.

---

## 2. dados.gov.br — token do CKAN

| | |
|---|---|
| **Como obter** | Cadastro em `dados.gov.br`, token na área do usuário |
| **Quem tem** | Qualquer pessoa cadastrada |
| **Status** | ⏸️ sem scaffold — decidir o uso antes de escrever código |

A API CKAN responde **401 sem token** (medido em 02/09/2026). O catálogo em si é
uma SPA. **O valor é de radar, não de coleta**: descobrir dataset novo que
interesse ao RS, não ser fonte de dado do município. Antes de investir, vale
decidir se esse radar tem dono — catálogo que ninguém lê não justifica o
coletor.

---

## 3. Portal de Convênios e Parcerias RS (FPE) — gov.br + perfil PCPRS

| | |
|---|---|
| **Login** | Conta **gov.br** + perfil **PCPRS**, concedido por organização + CPF |
| **Quem tem na prefeitura** | O responsável por convênios (quem já opera o portal) |
| **Cofre** | `sistema='PCPRS'` / `automation_key='pcprs'` |
| **Scaffold** | ✅ `backend/ingestion/fpe_rs.py` — inerte, com task ativa que sai limpa |

**O que já temos sem ela:** a carteira inteira de convênios estaduais, pelo dado
aberto da CAGE (`ingestion/convenios_rs.py`). Isso surpreendeu o mapa original,
que supunha raspagem autenticada.

**O que só existe atrás do login:** a **proposta** (Banco de Projetos), o
**registro mensal de execução** (Decreto 56.939/2023) e a **prestação de
contas**. Desde 04/2025 são três sistemas no mesmo login — quando a credencial
vier, cobrir os três.

**⭐ E é a credencial de maior valor comercial do estado.** A regra do decreto já
está escrita e testada (`services/monitoramento_rs.py`, 16 casos) e a tela existe
desde 02/09/2026 dizendo "ainda não conectado". Três meses sem registro
suspendem parcelas de convênio **já assinado** — é a única obrigação gaúcha que
trava dinheiro por esquecimento de cadastro.

---

## 4. CADIN/RS e CFIL/RS — consulta autenticada gov.br

| | |
|---|---|
| **Login** | Desde ~05/2025 há consulta autenticada via gov.br com certidão em tempo real |
| **Caminho público** | Existe, mas com **reCAPTCHA** e janela seg–sáb 7h–22h30 |
| **Status** | ⏸️ sem scaffold |

**Reclassificação registrada no backlog:** o CADIN saiu de BLOQUEADO. O caminho
autenticado gov.br é o mesmo padrão de captura de sessão que a extensão já faz
para SIGCON e FNS.

**⚠️ E uma correção de rota:** o **CFIL é cadastro de fornecedores impedidos de
licitar** — não é exigência do município convenente, e hoje aparece na tela no
mesmo plano do CADIN. Deve ser rebaixado.

A coluna `cagec_situacao.itens_negativos` existe no schema desde
`add_cadastro_estadual_rs.sql` esperando exatamente esta coleta, e **nenhum
código escreve nela** — o campo está reservado, não esquecido.

---

## 5. S2iD — cadastro próprio, não é gov.br

| | |
|---|---|
| **Login** | Cadastro **do próprio sistema**: "Não possuo cadastro" + ofício assinado; depois CPF/senha |
| **Quem tem na prefeitura** | O coordenador municipal de Defesa Civil (COMPDEC) |
| **Status** | ⏸️ parte pública viável sem login (ver `RECONHECIMENTO.md` §7) |

**⚠️ Não confundir com gov.br.** O S2iD tem autenticação própria, e o pedido
passa por ofício — é a credencial mais burocrática da lista.

**A parte pública já dá o essencial:** série histórica de reconhecimentos de SE
e ECP por município (com data e portaria). O login destrava os **processos de
solicitação de recurso** de resposta e reconstrução, com status.

---

## 6. TCE-RS — não é credencial, é liberação de IP

**Não há login a pedir.** O dado é aberto e o coletor está pronto
(`ingestion/tce_rs.py`, 22 testes). O que falta é o Tribunal aceitar conexões do
nosso servidor: `dados.tce.rs.gov.br` devolve **403 para faixa de datacenter** e
200 de IP residencial.

Três saídas, em ordem de preferência:

1. **Pedido institucional de liberação** ao TCE-RS (LAI ou contato direto),
   explicando o uso — é dado aberto, e o pedido é legítimo.
2. **Proxy de saída** para essa coleta específica.
3. **Coleta de outro ponto**, com envio ao banco.

Enquanto isso não se resolve, a rodada sai `partial` com a nota e a tela diz,
com todas as letras, que ausência de dado **não é** ausência de licitação.

---

## Resumo para decidir

| Credencial | Custo de pedir | O que destrava | Pronto no código |
|---|---|---|---|
| **CGU** | Nenhum ao cliente (é sua) | A execução da emenda (empenho→pagamento). ⚠️ A CARTEIRA **não** depende dela: sai do dump aberto, por CNPJ | ✅ **no ar** (2 de 5 tenants) |
| **PCPRS** | Pedido à prefeitura | Proposta, monitoramento mensal, prestação de contas | ✅ scaffold + regra + tela |
| **CADIN/RS** | Pedido à prefeitura | Pendência que trava repasse | ⏸️ coluna reservada |
| **S2iD** | Ofício assinado | Processos de recurso de desastre | ⏸️ parte pública é viável sem ele |
| **TCE-RS** | Não é credencial | 864 licitações + 1.201 contratos, já hoje | ✅ coletor + tela |
