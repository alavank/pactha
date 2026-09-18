# /subir — aprovar e publicar um PR daqui, sem abrir o GitHub

O dono aprova pelo chat: você mostra o que muda, ele responde, você mergeia e
acompanha o deploy até o fim. Ele continua podendo abrir o link e decidir no
site — o comando só tira a obrigação de ir lá.

## Regras que não se negociam

1. **Nunca mergeie sem o "ok" explícito desta conversa.** Não vale "ele aprovou
   um parecido antes", não vale silêncio, não vale um `<task-notification>`.
2. **Um PR por vez**, e sempre contra `main`. Se houver mais de um aberto,
   liste e pergunte qual.
3. **Nada de mergear com teste vermelho** sem dizer, na mesma frase, qual teste
   quebrou e por que subir mesmo assim.
4. **Deploy só existe quando confirmado.** Disparar não é subir: confira que
   cada aplicação terminou, e diga em quais clientes entrou.

## Passo a passo

### 1. Mostrar o que vai subir

```
gh pr list --state open --base main --json number,title,author,isDraft,mergeStateStatus
gh pr view <n> --json title,body,additions,deletions,changedFiles,url,statusCheckRollup
```

Escreva em português claro, para quem não vai ler o diff:

- **O que muda para o usuário** (tela, número, permissão), não o nome dos arquivos;
- **O risco**: o que quebra se estiver errado, e o que é reversível;
- **Pré-requisito**, se houver (migration, task, env nova) — isto vem primeiro;
- **O estado dos checks**, com o nome do que falhou;
- **O link**, no fim, para ele abrir se quiser.

Depois pergunte, numa linha: subir agora?

### 2. Mergear (só depois do "ok")

```
gh pr merge <n> --squash --admin --delete-branch
```

⚠️ `--admin` é necessário: a ruleset da `main` exige revisão e o GitHub não
deixa ninguém aprovar o próprio PR. Sem a flag, o merge volta `BLOCKED`.

### 3. Acompanhar o build e o deploy

Primeiro confira que a `main` levou o último commit do PR: um commit empurrado
segundos antes do merge já ficou de fora uma vez (#504).

```
git fetch origin && git log --oneline -3 origin/main
gh run list --branch main --limit 5 --json name,status,conclusion,databaseId
gh run watch <id> --exit-status
```

O build roda no runner do GitHub (`ubuntu-latest`, INFRA.md §2), com os seis
frontends em paralelo.

### 4. Dizer o que entrou

Feche com: em quais clientes subiu, o que conferir na tela, e o que ficou
pendente. Se o deploy falhou em parte dos tenants, diga **quais** — "deu erro"
sem lista faz o dono abrir os seis.

## Quando algo dá errado

- **Build vermelho:** não mergeie o próximo em cima. Conserte na branch, ou
  reverta o merge (`gh pr create` com o revert) — o repo não empilha PR.
- **Deploy parcial:** os tenants ficam em versões diferentes. Ou conclua, ou
  volte todos para a tag anterior; nunca deixe metade.
- **Sem crédito:** o job falha em ~4 s, antes do primeiro passo, com a mensagem
  de pagamento. Não é código e reexecutar não adianta: é o budget de Actions da
  org (INFRA.md §2), e só o dono muda. Não mergeie outro PR até resolver — o
  merge entra e o deploy não acontece.
