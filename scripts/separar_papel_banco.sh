#!/usr/bin/env bash
# ============================================================================
# CAMADA 3 DA AUDITORIA — a aplicação passa a conectar com um papel que NÃO
# consegue alterar a trilha. Roda NO SERVIDOR (o banco não aceita conexão de
# fora: `is_public=False`).
#
# O QUE ISTO MUDA, EM UMA FRASE
# -----------------------------
# Hoje o gatilho recusa `UPDATE`/`DELETE` em `audit_log` — mas o gatilho é do
# dono do banco, e quem tem a senha do dono pode removê-lo. Depois disto, a
# aplicação conecta como `pactha_app`, que simplesmente NÃO TEM esses poderes:
# a recusa passa a vir do sistema de permissões, antes do gatilho, e derrubar o
# gatilho deixa de ser uma saída (para derrubá-lo também falta permissão).
#
# ⚠️ POR QUE ISTO É SEGURO DE RODAR AGORA (conferido no código, não suposto):
#   · `DATABASE_URL_SYNC` JÁ EXISTE e aponta para o dono `pactha`. É o
#     pré-requisito que trancaria a aplicação fora do banco: as migrations do
#     boot fazem DDL e continuam precisando do dono. Sem essa variável, trocar
#     só `DATABASE_URL` faria o primeiro `ALTER TABLE` do boot morrer.
#   · NENHUM código Python chama `audit_log_podar` nem `audit_log_selar` (são
#     `SECURITY DEFINER` e continuam sem GRANT para a aplicação — dá-las
#     devolveria por dentro o poder que o REVOKE tira).
#   · NENHUM `UPDATE`/`DELETE` em `audit_log` fora de migrations.
#   · Nenhum router ou service executa DDL em execução.
#
# COMO RODAR (no servidor, como root):
#     bash separar_papel_banco.sh ensaiar  trust    # só confere o estado de hoje
#     bash separar_papel_banco.sh aplicar  trust    # cria o papel e ajusta os grants
#     bash separar_papel_banco.sh conferir trust    # prova o resultado
#     bash separar_papel_banco.sh desfazer trust    # apaga o papel (volta ao de hoje)
#
# O segundo argumento é o TENANT: montesiao | trust | freitas.
#
# A SENHA é gerada aqui e NÃO aparece na tela: sai só para o arquivo
# `/root/pactha_app.url`, com permissão 600. É de lá que você copia a
# `DATABASE_URL` nova para o Coolify.
# ============================================================================
set -euo pipefail

BANCO="pactha"        # nome do banco e do papel DONO (ver DATABASE_URL)
DONO="pactha"
NOVO="pactha_app"

# ⭐ QUAL TENANT. O container do Postgres é o hostname que aparece na
# `DATABASE_URL` daquele cliente — e é por isso que ele entra como PARÂMETRO, e
# não como palpite: os três bancos são idênticos por dentro, e um roteiro que
# "descobre" o container sozinho acerta o cliente errado com a mesma facilidade
# com que acerta o certo. Aqui, errar exige digitar o nome errado.
TENANT="${2:-}"
case "$TENANT" in
  montesiao)  CONTAINER="iogvjlnkpqlugja9j76rktl1" ;;
  trust)      CONTAINER="p434vbj35siee57shlsyzuc2" ;;
  freitas)    CONTAINER="tox59kvmkrb0ywmeaty3t02a" ;;
  # Santa Maria/RS (4o tenant, aberto em 16/08/2026). E o melhor lugar para
  # ESTREAR a Camada 3: banco novo, sem uso real ainda — o CONTINUAR.md §6.4
  # pede para nao comecar por montesiao, que e prefeitura em producao.
  santamaria) CONTAINER="m2ypghl41lbqhv7rdqzffdi3" ;;
  # BGK Assessoria/RS (6o tenant, aberto em 08/09/2026).
  bgk)        CONTAINER="evdmnadr2iiwqhjvnzvqrgvs" ;;
  *)
    echo "uso: bash $0 {ensaiar|aplicar|conferir|desfazer} {montesiao|trust|freitas|santamaria|bgk}" >&2
    exit 2
    ;;
esac
# A senha de cada tenant no seu próprio arquivo — misturar as três num só
# tornaria impossível girar a de um sem mexer nas outras.
SAIDA="/root/pactha_app_${TENANT}.url"

achar_container() {
  if ! docker ps --format '{{.Names}}' | grep -qx "$CONTAINER"; then
    echo "ERRO: container '$CONTAINER' ($TENANT) não está de pé." >&2
    docker ps --format '{{.Names}}\t{{.Image}}' | grep -i postgres >&2 || true
    exit 1
  fi
  echo "$CONTAINER"
}

psql_dono() {
  docker exec -i "$(achar_container)" psql -U "$DONO" -d "$BANCO" -v ON_ERROR_STOP=1 "$@"
}

# ---------------------------------------------------------------------------
# A CONFERÊNCIA NÃO ESCREVE NADA na trilha.
#
# O jeito "óbvio" de testar seria inserir uma linha e tentar alterá-la. Mas a
# trilha é append-only e imutável: essa linha de teste ficaria lá para sempre,
# num registro que é prova documental para o setor público. `has_privilege`
# responde a mesma pergunta consultando o catálogo do Postgres — e responde
# melhor, porque descreve o PODER, e não o resultado de uma tentativa.
# ---------------------------------------------------------------------------
CONSULTA_ESTADO="
SELECT
  EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '${NOVO}')          AS papel_existe,
  has_table_privilege('${NOVO}','audit_log','INSERT')                AS grava_trilha,
  has_table_privilege('${NOVO}','audit_log','SELECT')                AS le_trilha,
  has_table_privilege('${NOVO}','audit_log','UPDATE')                AS ALTERA_trilha,
  has_table_privilege('${NOVO}','audit_log','DELETE')                AS APAGA_trilha,
  has_table_privilege('${NOVO}','users','UPDATE')                    AS opera_o_resto,
  has_function_privilege('${NOVO}','audit_log_conteudo(audit_log)','EXECUTE')   AS confere_integridade,
  has_function_privilege('${NOVO}','audit_log_hash(text,text)','EXECUTE')       AS calcula_hash,
  has_function_privilege('${NOVO}','audit_log_podar(timestamptz,text,text,text[])','EXECUTE') AS PODE_PODAR;
"

case "${1:-}" in
  ensaiar)
    echo "== container: $(achar_container)"
    echo "== papéis de login hoje:"
    psql_dono -c "SELECT rolname, rolsuper, rolcreatedb FROM pg_roles WHERE rolcanlogin ORDER BY rolname;"
    echo "== o papel novo já existe?"
    psql_dono -tAc "SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='${NOVO}');"
    echo "== dono das funções e do gatilho da trilha:"
    psql_dono -c "SELECT proname, pg_get_userbyid(proowner) AS dono, prosecdef AS security_definer
                    FROM pg_proc WHERE proname LIKE 'audit\\_log\\_%' ORDER BY proname;"
    ;;

  aplicar)
    SENHA=$(openssl rand -base64 30 | tr -d '/+=' | head -c 32)
    echo "== criando ${NOVO} (a senha não aparece aqui; vai para ${SAIDA})"
    psql_dono <<SQL
DO \$\$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '${NOVO}') THEN
    CREATE ROLE ${NOVO} LOGIN PASSWORD '${SENHA}';
  ELSE
    ALTER ROLE ${NOVO} WITH LOGIN PASSWORD '${SENHA}';
  END IF;
END
\$\$;

GRANT CONNECT ON DATABASE ${BANCO} TO ${NOVO};
GRANT USAGE   ON SCHEMA public      TO ${NOVO};

-- O resto do sistema segue funcionando por inteiro: a aplicação continua
-- criando, editando e apagando convênio, usuário, anotação, tudo.
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES    IN SCHEMA public TO ${NOVO};
GRANT USAGE, SELECT                  ON ALL SEQUENCES IN SCHEMA public TO ${NOVO};

-- ⚠️ TABELA QUE AINDA NÃO EXISTE também precisa nascer acessível. Sem estas
-- duas linhas, a próxima migration criaria uma tabela que a aplicação não
-- enxerga — e o sintoma seria "permission denied" numa tela nova, semanas
-- depois, longe daqui.
ALTER DEFAULT PRIVILEGES FOR ROLE ${DONO} IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO ${NOVO};
ALTER DEFAULT PRIVILEGES FOR ROLE ${DONO} IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO ${NOVO};

-- ⭐ O PONTO DE TUDO: a trilha vira SÓ-INSERT para a aplicação.
REVOKE UPDATE, DELETE, TRUNCATE ON audit_log FROM ${NOVO};
GRANT  SELECT, INSERT            ON audit_log TO ${NOVO};
GRANT  USAGE, SELECT ON SEQUENCE audit_log_id_seq TO ${NOVO};

-- Conferir a integridade: pode. Sem estes dois GRANT, a aplicação continua
-- gravando normalmente e o botão "Verificar integridade" passa a falhar — o
-- erro que só aparece no dia em que alguém foi conferir.
GRANT EXECUTE ON FUNCTION audit_log_conteudo(audit_log) TO ${NOVO};
GRANT EXECUTE ON FUNCTION audit_log_hash(text, text)    TO ${NOVO};
SQL

    umask 077
    printf 'DATABASE_URL=postgresql+asyncpg://%s:%s@%s:5432/%s\n' \
      "${NOVO}" "${SENHA}" "${CONTAINER}" "${BANCO}" > "${SAIDA}"
    chmod 600 "${SAIDA}"
    echo "== pronto. A URL nova está em ${SAIDA} (só root lê)."
    echo "== NÃO troque o DATABASE_URL_SYNC: ele continua no dono ${DONO},"
    echo "   porque as migrations do boot fazem DDL."
    ;;

  conferir)
    echo "== o que ${NOVO} pode, segundo o catálogo do Postgres:"
    psql_dono -x -c "${CONSULTA_ESTADO}"
    echo
    echo "ESPERADO:  grava_trilha=t · le_trilha=t · ALTERA_trilha=f · APAGA_trilha=f"
    echo "           opera_o_resto=t · confere_integridade=t · calcula_hash=t · PODE_PODAR=f"
    ;;

  desfazer)
    echo "== devolvendo tudo ao estado de hoje (o papel some; o dono nunca mudou)"
    psql_dono <<SQL
REVOKE ALL ON ALL TABLES    IN SCHEMA public FROM ${NOVO};
REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM ${NOVO};
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA public FROM ${NOVO};
REVOKE ALL ON SCHEMA public FROM ${NOVO};
REVOKE ALL ON DATABASE ${BANCO} FROM ${NOVO};
ALTER DEFAULT PRIVILEGES FOR ROLE ${DONO} IN SCHEMA public
    REVOKE SELECT, INSERT, UPDATE, DELETE ON TABLES FROM ${NOVO};
ALTER DEFAULT PRIVILEGES FOR ROLE ${DONO} IN SCHEMA public
    REVOKE USAGE, SELECT ON SEQUENCES FROM ${NOVO};
DROP ROLE IF EXISTS ${NOVO};
SQL
    rm -f "${SAIDA}"
    echo "== desfeito. Lembre de voltar o DATABASE_URL no Coolify se já tinha trocado."
    ;;

  *)
    echo "uso: bash $0 {ensaiar|aplicar|conferir|desfazer} {montesiao|trust|freitas}" >&2
    exit 2
    ;;
esac
