# ⚠️ Esta pasta está DESATIVADA

O **Painel Executivo** que morava aqui (app Next.js separado, imagem
`painel-montesiao-mg`, aplicação Coolify `montesiao-mg-painel`) **não é mais
usado**. Tudo que ele fazia passou para o frontend principal:

| Antes (`painel/`) | Agora (`frontend/`) |
|---|---|
| app separado em `https://pactha-montesiao-mg-painel-…` | mesmo app do sistema |
| `/app` (visão do prefeito) | `/dashboard` — **Painel de Indicadores** |
| `/tv` (gestão à vista) | `/tela` — **Modo Tela** (abre em janela separada) |
| login próprio | mesmo login do PACTHA |
| build próprio no CI | nenhum — um build a menos por push |

Motivo: eram duas bases para a mesma informação, dois deploys e dois logins.
O módulo BI nativo (`NEXT_PUBLIC_BI_MODULE=1`) cobre o caso de uso inteiro,
com o Modo Tela abrindo numa janela própria a partir do próprio painel.

**Esta pasta não é buildada por nenhum workflow e não é servida em lugar
nenhum.** Ela segue no repositório apenas como referência histórica enquanto a
migração é validada em produção; pode ser removida por completo em seguida.
