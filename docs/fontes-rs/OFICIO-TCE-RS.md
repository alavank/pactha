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

> **Assunto:** Solicitação de liberação de acesso automatizado aos serviços de
> dados abertos do Tribunal (`dados.tce.rs.gov.br` e `portal.tce.rs.gov.br`)

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

Os conjuntos de dados do LicitaCon, do LicitaCon Obras e da execução
orçamentária municipal, publicados por este Tribunal, são acessíveis por
navegador e por requisição automatizada a partir de conexões residenciais.
Contudo, requisições originadas do endereço IP **54.232.208.118** (servidor em
nuvem localizado em São Paulo/SP) recebem, de forma consistente, resposta
**HTTP 403 (Forbidden)**.

O comportamento foi verificado em quatro ocasiões independentes — **17 de
agosto, 29 de agosto e 3 de setembro de 2026 (duas medições neste último dia)**
— e alcança **os dois serviços**, em endereços distintos:

*Portal de Dados Abertos (`dados.tce.rs.gov.br`)*

- `/api/3/action/package_show?id=licitacoes-pm-de-nova-palma`
- `/dados/licitacon/licitacao/orgao/53100.csv.zip`
- `/dados/municipal/empenhos/2026/53100.csv.zip`

*Serviços de consulta (`portal.tce.rs.gov.br`)*

- `/api/qonws/q/licitacon_dominios.orgaos.json`
- `/api/qonws/q/licitacon.remessas.json`
- `/api/obras/v1/orgaos-fiscalizados`
- `/api/obras/v1/orgaos/88488366000100/obras`

Nos dois serviços a resposta é idêntica — mesmo corpo (199 bytes, página padrão
"403 Forbidden") e mesmo tempo de resposta (0,08 a 0,09 segundo) —, o que sugere
tratar-se de **uma única regra aplicada na borda da rede**, e não de
configuração de cada aplicação.

Na mesma bateria de testes, e a partir do mesmo endereço IP e no mesmo minuto,
outros portais públicos estaduais responderam normalmente (`HTTP 200` em 0,35
segundo, no caso do CHE/SEFAZ-RS), o que indica que a recusa não decorre de
indisponibilidade de rede. Todos os endereços acima respondem `HTTP 200` quando
acessados de conexão residencial.

Presume-se tratar-se de regra genérica de proteção aplicada a faixas de
endereços de datacenter, e não de restrição dirigida a este solicitante.

**2. Da finalidade**

Os dados destinam-se a compor painel de acompanhamento de convênios, contratos e
transferências voluntárias utilizado por **prefeituras gaúchas**, entre elas a de
**[MUNICÍPIO]**, permitindo ao próprio ente municipal acompanhar seus atos de
licitação e contratação ao lado dos repasses federais e estaduais que os
originam.

Merece registro específico o **LicitaCon Obras**: o campo de origem do recurso,
ali informado pelo próprio órgão fiscalizado, é o único registro público que
vincula uma obra municipal ao convênio ou repasse que a financiou. É justamente
esse vínculo que permite ao gestor municipal — e ao controle interno da
prefeitura — acompanhar a execução física e financeira de cada obra ao lado do
instrumento que a originou, finalidade convergente com a do próprio sistema
instituído pela Resolução nº 1.176/2023 deste Tribunal.

Não há redistribuição comercial dos dados brutos, tampouco tratamento de dados
pessoais: os conjuntos utilizados referem-se a atos administrativos de pessoas
jurídicas de direito público.

**3. Do compromisso técnico**

O acesso, se liberado, observará as seguintes práticas, já implementadas:

- **Requisições condicionais** (`If-None-Match` / `If-Modified-Since`) nos
  arquivos, de modo que conteúdo inalterado não seja transferido novamente;
- **Uma única rodada diária**, em horário de baixa demanda (madrugada), limitada
  aos órgãos dos municípios atendidos;
- **Intervalo mínimo de meio segundo entre requisições**, com teto de tempo por
  rodada e retomada na noite seguinte, de modo que a carga inicial se distribua
  por vários dias em vez de concentrar-se em um;
- Busca de detalhe **apenas para registros novos ou alterados** desde a rodada
  anterior, aferida pelo campo de atualização informado pelo próprio serviço;
- **Identificação do agente** em todas as requisições;
- Respeito a limites de taxa e interrupção imediata mediante solicitação deste
  Tribunal.

Em regime estável, o volume estimado é de **algumas dezenas de requisições por
município por dia**. A carga inicial é maior — da ordem de dois mil registros
para um município de pequeno porte e doze mil para um de médio porte —, e é
justamente por isso que se propõe distribuí-la ao longo de vários dias.

**4. Do pedido**

Diante do exposto, solicito:

**a)** a liberação do endereço IP **54.232.208.118** para acesso aos serviços
`dados.tce.rs.gov.br` e `portal.tce.rs.gov.br`; ou, alternativamente,

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

> Requisições automatizadas aos serviços de dados abertos do Tribunal
> (`dados.tce.rs.gov.br` e `portal.tce.rs.gov.br`) originadas do IP
> 54.232.208.118 recebem HTTP 403 de forma consistente, verificado em 17/08,
> 29/08 e 03/09/2026, tanto nos arquivos do LicitaCon
> (`/dados/licitacon/licitacao/orgao/{código}.csv.zip`) quanto nas APIs de
> consulta (`/api/qonws/q/...` e `/api/obras/v1/...`). Nos dois serviços a
> resposta é idêntica em corpo e em tempo (0,08 s), o que sugere regra única de
> borda. Os mesmos endereços respondem HTTP 200 a partir de conexões
> residenciais, e outros portais estaduais respondem normalmente do mesmo IP no
> mesmo minuto — o que sugere filtro aplicado a faixas de datacenter.
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
