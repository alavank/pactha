# Pedido de liberação de acesso automatizado — TCE-RS

> **Como usar.** O texto da §2 é o ofício, pronto para enviar. Substitua o que
> está entre colchetes. A §3 é a versão curta, para formulário eletrônico com
> limite de caracteres. A §1 explica as escolhas de redação — leia antes de
> editar, porque duas delas são deliberadas.

---

## 1. Três decisões de redação, e por que elas importam

**Não se pede "exceção", pede-se acesso ao que já é público.** O dado do
LicitaCon já está publicado em `dados.tce.rs.gov.br`. O que existe é um filtro
de rede que impede o acesso automatizado — e a LAI garante exatamente esse
acesso. O tom certo é o de quem aponta um efeito colateral, não o de quem pede
favor.

**Não se acusa bloqueio deliberado.** É quase certo que o 403 venha de uma regra
genérica de WAF contra faixas de datacenter, e não de uma decisão sobre este
sistema. O ofício descreve o comportamento observado e deixa a causa em aberto —
afirmar intenção põe o servidor na defensiva sem necessidade.

**A finalidade é declarada com todas as letras.** O pedido de um CNPJ privado
para acessar dado público em volume é legítimo, e omitir a finalidade é o que o
tornaria suspeito. Dizer que o destinatário é uma prefeitura gaúcha que fiscaliza
os próprios atos ajuda o pedido, não atrapalha.

---

## 2. Ofício

> **Assunto:** Solicitação de liberação de acesso automatizado ao Portal de Dados
> Abertos (`dados.tce.rs.gov.br`)

Ao Tribunal de Contas do Estado do Rio Grande do Sul
[Ouvidoria / Serviço de Informação ao Cidadão — SIC]

**Solicitante:** [RAZÃO SOCIAL], CNPJ [00.000.000/0001-00]
**Responsável:** [NOME COMPLETO], [CARGO]
**Contato:** [E-MAIL] · [TELEFONE]
**Data:** [DD/MM/AAAA]

---

Prezados Senhores,

Venho, com fundamento na **Lei nº 12.527/2011 (Lei de Acesso à Informação)**,
em especial no **art. 8º, §3º, incisos II e III**, que determina aos órgãos
públicos possibilitar "a gravação de relatórios em diversos formatos
eletrônicos, inclusive abertos e não proprietários" e "o **acesso automatizado
por sistemas externos** em formatos abertos, estruturados e legíveis por
máquina", solicitar a liberação de acesso programático ao Portal de Dados
Abertos deste Tribunal.

**1. Do objeto**

Os conjuntos de dados do LicitaCon e da execução orçamentária municipal,
publicados em `dados.tce.rs.gov.br`, são acessíveis por navegador e por
requisição automatizada a partir de conexões residenciais. Contudo, requisições
originadas do endereço IP **54.232.208.118** (servidor em nuvem localizado em
São Paulo/SP) recebem, de forma consistente, resposta **HTTP 403 (Forbidden)**.

O comportamento foi verificado em três ocasiões independentes — **17 de agosto,
29 de agosto e 3 de setembro de 2026** — nos seguintes endereços:

- `https://dados.tce.rs.gov.br/api/3/action/package_show?id=licitacoes-pm-de-nova-palma`
- `https://dados.tce.rs.gov.br/dados/licitacon/licitacao/orgao/53100.csv.zip`
- `https://dados.tce.rs.gov.br/dados/municipal/empenhos/2026/53100.csv.zip`

Na mesma bateria de testes, e a partir do mesmo endereço IP, outros portais
públicos estaduais responderam normalmente (`HTTP 200`), o que indica que a
recusa é específica deste servidor e não decorre de indisponibilidade de rede.
Os mesmos endereços respondem `HTTP 200` quando acessados de conexão
residencial.

Presume-se tratar-se de regra genérica de proteção aplicada a faixas de
endereços de datacenter, e não de restrição dirigida a este solicitante.

**2. Da finalidade**

Os dados destinam-se a compor painel de acompanhamento de convênios, contratos e
transferências voluntárias utilizado por **prefeituras gaúchas**, entre elas a de
**[MUNICÍPIO]**, permitindo ao próprio ente municipal acompanhar seus atos de
licitação e contratação ao lado dos repasses federais e estaduais que os
originam.

Não há redistribuição comercial dos dados brutos, tampouco tratamento de dados
pessoais: os conjuntos utilizados referem-se a atos administrativos de pessoas
jurídicas de direito público.

**3. Do compromisso técnico**

O acesso, se liberado, observará as seguintes práticas, já implementadas:

- **Requisições condicionais** (`If-None-Match` / `If-Modified-Since`), de modo
  que arquivos inalterados não sejam transferidos novamente;
- **Uma única rodada diária**, em horário de baixa demanda (madrugada), limitada
  aos órgãos dos municípios atendidos;
- **Identificação do agente** em todas as requisições;
- Respeito a limites de taxa e interrupção imediata mediante solicitação deste
  Tribunal.

O volume estimado é de **dois arquivos por município por dia**, com transferência
efetiva apenas quando houver publicação nova.

**4. Do pedido**

Diante do exposto, solicito:

**a)** a liberação do endereço IP **54.232.208.118** para acesso ao portal
`dados.tce.rs.gov.br`; ou, alternativamente,

**b)** a indicação do procedimento adequado para obtenção de acesso
automatizado — cadastro prévio, chave de identificação, endereço alternativo ou
limite de requisições a ser observado.

Caso a restrição decorra de política deliberada quanto ao acesso automatizado,
solicito que seja informada, para que este solicitante adeque seus
procedimentos.

Coloco-me à disposição para prestar esclarecimentos técnicos adicionais.

Respeitosamente,

**[NOME COMPLETO]**
[CARGO] — [RAZÃO SOCIAL]
[E-MAIL] · [TELEFONE]

---

## 3. Versão curta (formulário eletrônico do SIC)

> Requisições automatizadas ao portal de dados abertos
> (`dados.tce.rs.gov.br`) originadas do IP 54.232.208.118 recebem HTTP 403 de
> forma consistente, verificado em 17/08, 29/08 e 03/09/2026, nos endpoints do
> LicitaCon (`/dados/licitacon/licitacao/orgao/{código}.csv.zip`) e da execução
> orçamentária. Os mesmos endereços respondem HTTP 200 a partir de conexões
> residenciais, e outros portais estaduais respondem normalmente do mesmo IP —
> o que sugere filtro aplicado a faixas de datacenter.
>
> Os dados são utilizados em painel de acompanhamento de convênios e contratos
> para prefeituras gaúchas, e o acesso observa requisições condicionais
> (If-None-Match), rodada diária única em horário de baixa demanda e
> identificação do agente.
>
> Com fundamento no art. 8º, §3º, II e III da Lei 12.527/2011, que assegura o
> acesso automatizado por sistemas externos, solicito a liberação do IP
> 54.232.208.118 ou a indicação do procedimento adequado para acesso
> programático.

---

## 4. Onde enviar

O TCE-RS mantém canal de Ouvidoria e Serviço de Informação ao Cidadão em
`tcers.tc.br`. **Confirme o endereço e o formulário vigentes no site antes de
enviar** — este documento não os fixa de propósito, porque canal institucional
muda e um ofício enviado ao endereço errado volta como "não respondido".

Vale enviar **também** ao setor técnico responsável pelo portal de dados
abertos, se houver contato publicado: o pedido é operacional, e a Ouvidoria
costuma encaminhá-lo de qualquer modo.

## 5. Enquanto a resposta não vem

O coletor está pronto e testado (`backend/ingestion/tce_rs.py`, 22 testes) e a
Scheduled Task **não foi criada** — ligar é uma linha no Coolify no dia da
liberação. A tela `/dashboard/tce-rs` continua servindo o calendário de remessas
como conteúdo e diz, explicitamente, que a ausência de licitações na tela **não**
significa que o município não licitou.

As outras duas saídas seguem disponíveis, caso a resposta demore ou seja
negativa: proxy de saída dedicado a esta coleta, ou execução a partir de outro
ponto de rede com envio ao banco.
