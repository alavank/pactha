# Imutabilidade da trilha de auditoria — PACTHA

> **O que este documento é.** O modelo de proteção da tabela `audit_log`: o que o sistema
> garante hoje, o que ele **não** garante, e o passo a passo da **separação de papel no banco**
> — que é **decisão do dono** e **não foi aplicada**.
>
> Infra (Coolify na AWS Lightsail `54.232.208.118`, seis tenants): [`../INFRA.md`](../INFRA.md).
> Modelo de credenciais dos portais: [`SECURITY_CREDENTIALS.md`](SECURITY_CREDENTIALS.md).
>
> Pedido do dono, literal: os logs de auditoria *"são IMUTÁVEIS, não podem ser alterados ou
> editados ou excluídos, e devem atender à LGPD e às ISOs de segurança da informação"*.

---

## 1. O que está no ar

| Camada | O que faz | Onde |
|---|---|---|
| Superfície | A tela `/dashboard/auditoria` **não tem** botão de editar, excluir ou reclassificar. A API não expõe rota de escrita na trilha. | `frontend/src/app/dashboard/auditoria/page.tsx`, `backend/routers/auditoria.py` |
| Banco — append-only | `trg_audit_log_imutavel` (`BEFORE UPDATE OR DELETE`, por linha) e `trg_audit_log_truncate` (`BEFORE TRUNCATE`, por comando) levantam exceção. A tentativa **dá erro**, não passa em silêncio. | `backend/migrations/add_auditoria_imutavel.sql` |
| Banco — selo encadeado | `trg_audit_log_encadear` (`BEFORE INSERT`) calcula `hash = sha256(hash_anterior ‖ conteúdo da linha)` **dentro do Postgres** (`audit_log_hash`, `audit_log_conteudo`). Nem a aplicação escolhe o valor. | idem |
| Conferência | `GET /api/auditoria/integridade` refaz a corrente em lotes, **chamando as mesmas funções do banco** que o gatilho usa. Botão **Verificar integridade** na tela. | `backend/services/audit_integridade.py`, `backend/routers/auditoria.py` |
| Poda controlada | `audit_log_podar(p_ate, p_autor, p_motivo, p_prefixos)` — `SECURITY DEFINER`, marca uma variável de sessão que o gatilho respeita, exige autor, recusa corte no futuro, nunca poda o próprio livro-caixa da poda e **registra a poda na trilha na mesma transação**. | idem |

Retenção declarada pelo dono: **5 anos** para segurança, acesso e permissão; **12 meses** para
navegação. **O padrão de fábrica é não apagar nada** — não há job, não há cron, não há expurgo.

**A tela mostra o estado real das travas, não uma promessa.** A resposta da conferência traz
`protecoes.itens` lido do catálogo do Postgres a cada chamada: trava que alguém derrubou aparece
**Desligada**, em vermelho. Uma tela que jurasse "exclusão bloqueada" a partir de um texto fixo
diria a mesma coisa depois de o gatilho cair — que é exatamente o momento em que ela precisava
avisar.

---

## 2. Modelo de ameaça — o que garante e o que NÃO garante

Esta seção existe porque a frase "os logs são imutáveis" é falsa em qualquer sistema que guarde
os logs no mesmo banco que os dados. O que dá para dizer com precisão é isto:

| Quem tenta | Consegue alterar/apagar? | Fica detectável? |
|---|---|---|
| Usuário pela tela | **Não** — não existe superfície de escrita | n/a |
| Usuário com token/API | **Não** — não existe rota de escrita | n/a |
| Bug da aplicação (`UPDATE` acidental) | **Não** — o gatilho levanta exceção e a transação inteira falha | o erro aparece no log da API |
| Papel de aplicação sem `UPDATE/DELETE` (§4) | **Não** — barrado por privilégio, antes do gatilho | n/a |
| `SET session_replication_role = replica` | **Não** — os gatilhos que recusam são `ENABLE ALWAYS` | n/a |
| Quem tem a senha **dona** do banco (`pactha`) | **Sim** — pode `DROP TRIGGER` e depois alterar | **Sim** (ver abaixo) |
| Superusuário do Postgres / acesso ao volume | **Sim** | **Sim** (ver abaixo) |

**Sobre a linha do `session_replication_role`.** Gatilho nasce em modo *origin*, e nesse modo ele
**não dispara** quando a sessão está em papel de réplica. Isso faria do append-only um
interruptor de uma linha (`SET ...; UPDATE audit_log ...`), sem `DROP TRIGGER` para alguém notar
depois e desfeito sozinho ao fechar a conexão. Por isso os dois gatilhos que **recusam** são
`ENABLE ALWAYS`. O de **INSERT** continua em *origin*, de propósito: é o que permite que um
`pg_restore --disable-triggers` recoloque a trilha com os selos **originais** dela, em vez de
reassinar tudo na entrada — um backup restaurado tem de continuar conferindo contra o passado.

**Como fica detectável, em concreto.** A conferência distingue três coisas:

- **conteúdo** — o registro não bate com o próprio selo: ele foi **editado** depois de gravado;
- **elo** — o registro aponta para um antecessor diferente do que está lá: alguém **apagou uma
  linha do meio** ou trocou a ordem;
- **sem selo** — a linha entrou com a proteção desligada.

Para apagar uma linha do meio **sem** deixar rastro, seria preciso recalcular o selo de **todas**
as linhas seguintes — e para isso seria preciso conseguir dar `UPDATE` nelas. É esse encadeamento
que transforma "apagar uma linha" em "reescrever a trilha inteira".

**"Íntegra" vale para o registro inteiro? A conferência prova isso também.** A lista de colunas
que entram no selo é **fixa** (tem de ser: incluir coluna nova automaticamente invalidaria todos
os selos antigos de uma vez). O efeito colateral é que **acrescentar coluna a `audit_log` e
esquecer do selo** deixa aquele campo reescrevível sem quebrar elo nenhum — e a tela continuaria
dizendo "íntegra", com razão, sobre um subconjunto. Por isso a conferência **prova a cobertura**:
pega uma linha real, apaga um campo e pergunta ao banco o selo das duas versões; campo cujo selo
não muda **não entra na conta** e vira alerta no painel (`campos_fora_do_selo`). Lista vazia é o
estado normal e é o único em que "nenhum registro foi alterado" vale para o registro todo.
⚠️ Se um dia uma coluna precisar entrar no selo, isso é uma **versão `v2`** do conteúdo, valendo
dos ids novos em diante — reescrever selos antigos seria a aplicação reassinando o passado.

### A exceção conhecida — e ela é importante o bastante para estar na tela

Apagar os registros **mais recentes**, e só eles, **não quebra a corrente**: não existe elo
seguinte para denunciar a falta. A cadeia prova que nada foi alterado *no meio*; não prova que o
fim não foi cortado. Vale igual para **editar a última linha** e reselá-la: como nada aponta para
ela, o selo refeito fecha. É a mesma ponta, pelo mesmo motivo. Mitigações, em ordem de custo:

1. **Exportar o CSV periodicamente** (a tela já faz) e guardar fora do servidor — a cópia de
   ontem denuncia o corte de hoje. É a mitigação barata e é a recomendada agora.
2. **Âncora externa**: mandar o último selo do dia para fora (Telegram, e-mail, S3 com Object
   Lock, o Console Alavank). São 64 caracteres por dia. Não implementado.
3. Réplica só-leitura da trilha em outro servidor. Fora de escopo hoje.

> **Regra de redação para qualquer texto de tela sobre isto:** a corrente **denuncia**, não
> **impede**. Numa prefeitura esta tela pode ser citada num processo administrativo; uma frase a
> mais do que é verdade aqui é uma frase que alguém vai ter de defender lá.

---

## 3. Onde isso encosta na LGPD e na ISO 27001

Sem promessa de certificação — o que segue é o mapeamento honesto do que a trilha atende.

| Referência | O que pede | Como fica atendido |
|---|---|---|
| LGPD art. 37 | Registro das operações de tratamento | Uma linha por ato: quem, quando, de onde, sobre o quê, com que resultado |
| LGPD art. 46 | Medidas aptas a proteger de acesso não autorizado e de **alteração** | Append-only no banco + selo encadeado + conferência |
| LGPD art. 48 | Comunicação de incidente | A conferência transforma desconfiança em achado com data e número de registro |
| LGPD art. 18 | Direito de acesso do titular | `GET /api/auditoria/minha-atividade` |
| LGPD art. 16 | Não guardar além do necessário | Retenção declarada, poda deliberada e registrada |
| ISO/IEC 27001:2022 **A.8.15** Logging | Logs protegidos contra adulteração | §1 e §4 |
| ISO/IEC 27001:2022 **A.5.33** Proteção de registros | Registros protegidos de perda, destruição e falsificação | §1, §2, e a exportação como segunda cópia |
| ISO/IEC 27001:2022 **A.5.28** Coleta de evidência | Evidência preservada e verificável | A própria conferência entra na trilha (`auditoria.verificar_integridade`) |
| ISO/IEC 27001:2022 **A.8.2 / A.8.3** Acesso privilegiado e restrição de acesso | Separar quem opera de quem administra | **§4 — pendente, decisão do dono** |
| ISO/IEC 27001:2022 **A.8.16** Monitoramento | Detecção de comportamento anômalo | Criticidade por ação, filtro de falhas, travas exibidas na tela |

O item que falta para fechar A.8.2/A.8.3 é exatamente o da próxima seção.

---

## 4. ⚠️ SEPARAÇÃO DE PAPEL NO BANCO — **DECISÃO DO DONO, NÃO APLICADA**

### 4.1 O problema

Hoje existe **um** papel no Postgres: `pactha`, dono de tudo e usado pela aplicação. Ou seja, a
aplicação roda com o poder de derrubar o próprio gatilho que a impede de mexer na trilha. O
gatilho protege contra **erro**; não protege contra **quem tem a senha**.

O certo é a aplicação rodar com um papel que **não é dono** da `audit_log` e que **não tem**
`UPDATE`, `DELETE` nem `TRUNCATE` nela. Aí nem `DROP TRIGGER` é possível: derrubar gatilho é
privilégio de dono.

### 4.2 Por que isto não foi feito

Trocar a `DATABASE_URL` de um cliente vivo é mudança de **infra**, não de código. Se faltar um
privilégio qualquer, o sintoma é a aplicação **subir e não funcionar** — ou pior, funcionar pela
metade — em seis tenants, com prefeituras usando. **Não é para fazer sozinho e não é
para fazer sexta-feira.**

### 4.3 O SQL está na migration, e é ele que manda

O bloco pronto (criar o papel, todos os `GRANT`, o `REVOKE` da trilha e os dois `GRANT EXECUTE`
que a conferência precisa) vive comentado no fim de
[`backend/migrations/add_auditoria_imutavel.sql`](../backend/migrations/add_auditoria_imutavel.sql),
seção **"CAMADA 3"**. **Copie de lá, não daqui** — duas cópias do mesmo SQL em arquivos
diferentes divergem na primeira correção, e a que fica errada é sempre a que alguém colou às
pressas.

Três pontos desse bloco que costumam ser lidos rápido demais:

- **`GRANT EXECUTE ON FUNCTION audit_log_conteudo(audit_log)` e `audit_log_hash(text, text)`.**
  Sem os dois, a aplicação continua gravando normalmente e o botão **Verificar integridade**
  passa a falhar — a conferência chama essas funções como o papel da aplicação. É o erro que só
  aparece no dia em que alguém foi conferir.
- **`audit_log_podar` e `audit_log_selar` continuam sem `GRANT` para `pactha_app`.** As duas são
  `SECURITY DEFINER` (rodam como o dono): dar `EXECUTE` à aplicação devolveria por dentro
  exatamente o poder que o `REVOKE` tirou. A migration já faz
  `REVOKE ALL ... FROM PUBLIC` nas duas — sem isso, `PUBLIC` teria `EXECUTE` por padrão e o
  `REVOKE UPDATE, DELETE` seria decorativo.
- **`GRANT SELECT, INSERT ON audit_log` + `GRANT USAGE, SELECT ON SEQUENCE audit_log_id_seq`.**
  A trilha precisa continuar sendo **gravada**; o que ela deixa de aceitar é alteração.

### 4.4 O que a migration deixou em aberto — e a resposta

A migration fecha o passo dela com um alerta: *"as migrations de boot continuam precisando do
DONO (elas fazem DDL). Decidir ISTO antes do passo 3 — é a parte que trava o deploy se for
descoberta depois."* A resposta, conferida no código:

- **Não precisa de mudança de código.** Em `backend/services/startup.py`, **todo** o DDL do boot
  (`setup_db.create_tables()`, `Base.metadata.create_all()` e os arquivos de `MIGRATION_FILES`)
  roda em `sync_url = DATABASE_URL_SYNC or DATABASE_URL.replace("+asyncpg","")`. O runtime da API
  (SQLAlchemy async) roda em `DATABASE_URL`. São variáveis diferentes: basta apontar cada uma
  para um papel.
- **Nenhum router e nenhum service executa DDL em runtime** (varredura por `CREATE TABLE` /
  `ALTER TABLE` fora de `migrations/` e `setup_db.py`: zero ocorrências).
- **Só `services/audit.py` insere em `audit_log`.** Nenhum scraper de `ingestion/` toca a trilha.

| Env | Papel | Para quê |
|---|---|---|
| `DATABASE_URL_SYNC` | `pactha` (dono) | migrations e DDL do boot |
| `DATABASE_URL` | **`pactha_app`** (novo) | runtime da API |

> ⚠️ **A ordem importa, e é aqui que dá para trancar a aplicação fora do banco.**
> `DATABASE_URL_SYNC` **precisa existir e apontar para o dono ANTES** de `DATABASE_URL` mudar.
> Onde ela estiver vazia, o fallback usa a própria `DATABASE_URL`: trocar só essa faria as
> migrations rodarem como `pactha_app`, e o primeiro `ALTER TABLE` do boot morre com *permission
> denied*. O `.env.example` já traz a variável (linha 10) — confira **por tenant** no Coolify.

### 4.5 Passo a passo (por tenant)

1. **Ensaie num banco descartável, no mesmo servidor.** Não em outro cliente.

   A versão anterior deste passo mandava ensaiar em `freitas` ou `trust`. Está errado
   para este projeto: o dono determinou que **os outros clientes estão fora de escopo** —
   *"primeiro é fechar Monte Sião por completo; não vamos mexer em outros clientes"*.
   Ensaiar numa prefeitura que não pediu nada é criar risco para quem não participa da
   decisão.

   O ensaio equivalente, e que já foi usado neste repo para testar migration:

   ```bash
   ssh -i ~/.ssh/coolify_localhost root@54.232.208.118
   docker exec <db_uuid> psql -U pactha -d postgres -c "CREATE DATABASE ensaio_papel"
   # aplica o schema e a migration nova nele, cria o papel, roda os testes do passo 5
   docker exec <db_uuid> psql -U pactha -d postgres -c "DROP DATABASE ensaio_papel"
   ```

   O ensaio prova o que interessa — que os `GRANT`/`REVOKE` produzem exatamente os erros
   esperados — sem tocar em dado de cliente nenhum. O que ele **não** prova é a aplicação
   real conectando; isso só o passo 7 mostra, e é por isso que o backup do passo 2 existe.
2. **Backup antes de tudo:**
   ```bash
   ssh -i ~/.ssh/coolify_localhost root@54.232.208.118
   docker exec <db_uuid> pg_dump -U pactha -d pactha -Fc > /root/pactha-<tenant>-antes.dump
   ```
3. **Confirme `DATABASE_URL_SYNC`** na API e no worker (§4.4). Se estiver vazia, **pare aqui**,
   preencha com a URL do dono, redeploy, e só siga se o log do boot mostrar
   `[STARTUP] Startup migrations: N/N executadas`.
4. **Rode o SQL da CAMADA 3** como `pactha`:
   `docker exec -it <db_uuid> psql -U pactha -d pactha`.
5. **Teste o papel novo ANTES de ligá-lo na aplicação**, na mesma sessão:
   ```sql
   SET ROLE pactha_app;
   SELECT count(*) FROM audit_log;                                -- funciona
   INSERT INTO audit_log (action) VALUES ('teste.papel');         -- funciona
   UPDATE audit_log SET action='x' WHERE action='teste.papel';    -- ERRO: permission denied
   DELETE FROM audit_log WHERE action='teste.papel';              -- ERRO: permission denied
   TRUNCATE audit_log;                                            -- ERRO: permission denied
   SELECT audit_log_hash('', 'x');                                -- funciona (conferência)
   SELECT audit_log_podar(now() - interval '1 day', 'teste');     -- ERRO: permission denied
   RESET ROLE;
   ```
   Os erros são o resultado esperado. Se algum dos três primeiros **passar**, o `REVOKE` não
   pegou — não siga. A linha `teste.papel` fica na trilha e não sai: é append-only. Isso é o
   esperado, e ela é a prova de que o teste foi feito.
6. **Troque a `DATABASE_URL`** do resource da **API** (não do worker) para
   `postgresql+asyncpg://pactha_app:SENHA@<host_interno>:5432/pactha`:
   ```
   PATCH $B/applications/<api_uuid>/envs/bulk
   {"data":[{"key":"DATABASE_URL","value":"postgresql+asyncpg://pactha_app:...","is_build_time":false,"is_preview":false}]}
   ```
   ⚠️ O env do Coolify é **duplicado (produção + preview)** — o `envs/bulk` é upsert e não apaga
   as outras chaves, mas confira se a versão de preview não ficou com a URL velha.
7. **Redeploy da API** e leia o log do boot inteiro. Depois, **na aplicação**: entrar, abrir uma
   tela de cada módulo, criar e editar alguma coisa, revelar uma senha do Cofre, exportar o CSV
   da auditoria e clicar em **Verificar integridade**. O painel deve mostrar "Sem divergência"
   **e** a nota de papel deve mudar para *"A aplicação entra no banco com um usuário que não tem
   permissão de alterar nem de excluir esta tabela"* — é assim que se confirma, pela própria
   tela, que a camada entrou.
8. **Guarde a senha do dono no cofre**, fora do alcance de quem opera o dia a dia. Sem este
   passo, a separação protege menos do que parece.
9. **Pare aqui.** Os outros cinco tenants **não entram** enquanto o dono não
   disser. Eles não pediram esta mudança, e uma separação de papel malfeita derruba a API
   de quem está trabalhando. Quando entrarem, é o mesmo roteiro, um de cada vez.

### 4.6 Rollback

Voltar a `DATABASE_URL` do resource para a URL de `pactha` e redeployar. O papel `pactha_app`
pode continuar existindo — sem ninguém conectando com ele, não faz nada. Não há migration para
desfazer e nada no schema muda.

### 4.7 O que esta separação **não** resolve

- Os **workers de scraping** usam `DATABASE_URL_SYNC` (a do dono) e continuam com poder total.
  Nenhum deles toca `audit_log`, então cabe um terceiro papel (`pactha_worker`, sem privilégio
  nenhum na trilha) num segundo momento.
- Quem tem **SSH no servidor** continua alcançando o Postgres por `docker exec`. A separação
  protege a aplicação de si mesma e de quem só tem a credencial dela; não protege de quem tem a
  máquina.

---

## 5. Custo honesto: a corrente **serializa** as inserções

Cada `INSERT` precisa do selo da linha anterior, então duas inserções concorrentes não podem ser
calculadas ao mesmo tempo: elas se enfileiram num *advisory lock*. É o preço da corrente, e é
conhecido.

**Onde dói e onde não dói:**

- O sistema grava **centenas de eventos por dia** — na média, uma ordem de grandeza abaixo de um
  evento por segundo. O teto prático de uma cadeia serializada é a ordem de **algumas centenas de
  inserções por segundo** (uma busca por índice mais um sha256 de poucas centenas de bytes, sob
  um bloqueio curto). São **três a quatro ordens de grandeza de folga**. Neste volume, irrelevante.
- O sinal de que o dia chegou **não é o volume médio**, é a **espera por bloqueio**. Como a
  gravação acontece dentro do ciclo da requisição, o sintoma aparece como lentidão **em todas as
  telas ao mesmo tempo**, e não numa só — o que engana. Confirme antes de culpar a trilha:
  ```sql
  SELECT wait_event_type, wait_event, count(*)
    FROM pg_stat_activity
   WHERE state = 'active'
   GROUP BY 1,2 ORDER BY 3 DESC;
  ```
  Fila na trilha aparece como `wait_event_type = 'Lock'` em transações inserindo em `audit_log`.
- **O `id` sai da sequência duas vezes quando há corrida.** O `id` é atribuído pelo `DEFAULT`
  **antes** do gatilho rodar, então entre pegar o número e pegar o bloqueio cabe outra transação —
  e a linha entraria na corrente apontando para um elo de `id` **maior** que o dela. A conferência
  percorre em ordem de `id` e leria a inversão como *"apagaram um registro do meio"*: alarme falso
  **permanente**, impossível de limpar (limpar exigiria `UPDATE`). O gatilho detecta e tira um
  número novo já com o bloqueio na mão. O número descartado vira um **buraco na sequência**, que
  é inofensivo — a trilha já tem buracos de `id` por qualquer transação que deu *rollback*, e
  sequência nunca foi contagem.

**O que fazer se um dia crescer**, em ordem de custo:

1. **Cadeia por dia.** `hash_anterior` passa a ser o último selo **do mesmo dia**; as inserções
   de dias diferentes deixam de disputar a mesma ponta (o ganho real vem junto com particionar a
   tabela por dia). ⚠️ **Isso abre uma emenda por dia:** a fronteira entre dois dias deixa de ser
   provada. É preciso um **registro-âncora diário** — o selo final do dia anterior gravado como
   conteúdo do primeiro evento do dia seguinte — senão trocar um dia inteiro passa despercebido.
   A conferência muda junto, para validar N correntes **e** as âncoras.
2. **Tirar a gravação do ciclo da requisição** (fila em memória + gravador único). Resolve a
   latência percebida sem mexer na corrente, mas cria uma janela em que o evento existe e ainda
   não foi gravado — perda de auditoria em caso de queda. Trocar prova por velocidade numa trilha
   de auditoria só se decide com o dono.
3. **Âncora a cada N linhas** em vez de por linha. Barateia, mas passa a provar blocos, não
   linhas. Última opção.

---

## 6. Poda por retenção

- **Padrão de fábrica: não apagar nada.** Nada é automático, não há cron de poda.
- O `DELETE` só passa por `audit_log_podar(...)`, que abre a porta do gatilho **apenas para a
  própria transação**.
- **A poda vira um evento na trilha** (`auditoria.poda`), na **mesma transação** do `DELETE`:
  quantas linhas, até que data, com que filtro, por quem e por quê. Se a gravação falhar, o
  `DELETE` cai junto — não há poda silenciosa.
- **O vão fica explicável.** O evento guarda `hash_ultimo_podado`, o selo da última linha
  removida, que é para onde a próxima linha sobrevivente aponta. A conferência consegue então
  distinguir *"aqui houve um vão, e ele casa com a poda registrada no evento X"* de *"aqui alguém
  apagou linhas sem avisar"*. Um vão **sem** evento de poda que o explique é assinatura de
  remoção por fora.

### ⚠️ Poda **por prefixo** prova menos — e a tela diz isso

A política do dono tem duas janelas (5 anos para segurança, 12 meses para navegação), então a
poda de navegação usa `p_prefixos` e apaga linhas **salpicadas** no meio das que ficam. Cada
trecho removido vira um vão próprio, e **cada vão aponta para um selo diferente** — sendo que o
evento de poda só guardou o **último**. Nenhum desses vãos casa por selo.

Por isso o evento de poda também grava `faixa_contigua` (calculado pela função no momento do
`DELETE`) e a faixa `menor_id_removido`/`maior_id_removido`, e a conferência tem **duas provas**:

| Prova | Quando vale | O que ela afirma |
|---|---|---|
| **por selo** (forte) | poda contígua — um corte, um vão | o vão aponta exatamente para a última linha removida |
| **por faixa** (fraca) | só quando a poda **admite** ter deixado buracos | a poda declarou ter removido linhas nesse intervalo de ids |

A prova por faixa **não** distingue, *dentro do intervalo que a própria poda declarou
esburacado*, um trecho que a poda removeu de um que alguém removeu à mão. O que segura esse
flanco é que o evento de poda está na corrente, imutável, com autor, motivo e contagem — uma poda
inventada para acobertar remoção é, ela mesma, um registro a explicar. **A frase da tela diz que
a conferência foi por faixa**; não a encurte.

Sem esse caminho, a **primeira** poda de retenção por prefixo — um ato normal, pedido pelo dono —
deixaria o painel em alarme vermelho **permanente**: limpar exigiria `UPDATE` na trilha, que o
banco recusa.
- Quem executa: **operador, por psql, como `pactha`**. Não há tela e não há rota — por decisão,
  não por falta. Ver §4.3 sobre não conceder `EXECUTE` ao papel da aplicação.
- Antes de podar: **exporte o CSV do período** que vai sair. O registro da poda diz que 4.000
  linhas foram removidas; ele não diz o que estava nelas.

---

## 7. Texto de conformidade — onde ele vive

A nota de rodapé da tela vem do servidor (`GET /api/auditoria/catalogo` →
`aviso_imutabilidade` e `retencao.texto`), para a política não viver escrita em dois lugares.
A redação antiga —

> ~~"Os registros desta trilha são somente leitura: o sistema não oferece nenhuma forma de
> alterar ou excluir um evento já gravado."~~

— envelheceu para os **dois** lados: hoje o **banco** recusa a alteração (é mais do que ela
prometia) e existe um **caminho controlado de poda** (é menos do que ela prometia). A redação
atual, em `backend/routers/auditoria.py`, diz as três coisas — o que o banco recusa, o que o selo
denuncia, e o que continua possível para quem tem a senha de administrador.

⚠️ **O front tem uma cópia de reserva dessas duas frases** (usada só quando o catálogo não
responde), e ela **precisa continuar carregando a ressalva inteira**. É tentador encurtá-la
("a versão boa vem do servidor mesmo") — e é justamente no dia em que o catálogo falha que a
tela ficaria prometendo uma imutabilidade absoluta que o sistema não entrega. Mexeu numa,
mexa na outra: `frontend/src/app/dashboard/auditoria/page.tsx`, no rodapé da página.

A ressalva do painel de conferência (`RESSALVA_INTEGRIDADE`) segue a mesma regra e tem a mesma
cópia de reserva no front (`RESSALVA_RESERVA`).

---

## 8. Checklist para quem for revisar isto depois

- [ ] O botão **Verificar integridade** responde "Sem divergência" nos seis tenants.
- [ ] Nenhuma trava aparece **Desligada** no painel de conferência.
- [ ] Nenhum **campo fora do selo** aparece no painel (§2) — checar depois de toda migration que
      acrescente coluna a `audit_log`.
- [ ] `SELECT tgname, tgenabled FROM pg_trigger WHERE tgrelid = 'audit_log'::regclass` mostra
      `A` (always) nos dois gatilhos que recusam e `O` no de INSERT (§2).
- [ ] A nota de rodapé da tela e o `aviso_imutabilidade` do catálogo dizem a mesma coisa (§7).
- [ ] `DATABASE_URL_SYNC` está preenchida nos seis tenants (pré-requisito de §4).
- [ ] Decisão do dono sobre §4 (`pactha_app`): **pendente**.
- [ ] Exportação periódica do CSV para fora do servidor — a mitigação do corte de cauda (§2).
- [ ] Âncora externa do último selo do dia: não implementada; decidir se entra.
