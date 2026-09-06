# BANCO 2027

Sistema pessoal de inteligência de carreira: radar, perfil com níveis e evidências, análise de requisitos, prioridades de estudo, candidaturas, empresas, histórico e alertas.

## Implementado

- Frontend responsivo, tema claro/escuro, busca em requisitos, filtros persistentes, favoritos e comparação de até três vagas.
- Detalhes endereçáveis por hash para vagas e empresas; links continuam funcionando no GitHub Pages.
- Match por requisito obrigatório e diferencial; nível e evidência; inglês, experiência, formação e preferências. Requisitos não mapeados e elegibilidade afirmativa exigem confirmação individual. Não inferimos condições pessoais.
- Separação entre score atual, simulação de potencial, requisitos pendentes e impedimentos. “Aplicar agora” requer vaga ativa, elegível, >=80%, sem obrigatório ausente e sem pendências.
- Ranking de estudo, simulação de vagas desbloqueadas, esforço heurístico explícito e score de empresa.
- Pipeline com nove etapas, datas, feedback, próxima ação, observações, histórico de mudanças e taxas calculadas por candidaturas efetivamente registradas.
- Histórico semanal de mercado no coletor e de perfil ao acessar o painel, além de registro manual. Não inventa snapshots de semanas anteriores nem considera uma amostra sem confirmação como queda de mercado.
- Alertas no painel: match, backend júnior, empresa prioritária, Python+SQL+APIs e até um gap.
- Coletor Python preservado, extração por seções (obrigatório/diferencial), senioridade contraditória, deduplicação por similaridade >=0,90, IDs preservados e chave estável por fonte. Duplicatas e vagas excluídas permanecem no catálogo histórico, fora dos rankings.
- Verificação conservadora: 403/429/timeout/HTML genérico não significam vaga aberta ou encerrada. Status ativo expira após sete dias sem confirmação. 404/410, prazo expirado ou encerramento explícito marcam encerrada.
- Vercel API implementada para jobs, perfil/pipeline, match, atualização autenticada e acompanhamento da coleta.
- Supabase schema com tabelas de domínio, RLS por usuário, gravação transacional de estado pessoal, autenticação e limitação persistente de atualização.

## Estado de ativação

O frontend funciona no GitHub Pages usando a cópia pública `jobs.json`; os arquivos JavaScript antigos são fallback. Perfil e candidaturas ficam **em rascunho neste navegador** até conectar o Supabase. Há exportação/restauração de backup; nada pessoal é enviado ao repositório.

A migração para um banco online e o backend **ainda precisam de configuração e implantação externas**. Não há URL Vercel nem projeto Supabase preenchidos. Não foram criadas contas, senhas, serviços pagos ou chaves. O botão informa essa dependência; não simula coleta bem-sucedida.

Os 55 registros existentes foram preservados. A verificação neste ambiente não conseguiu confirmar anúncios ativos; anúncios sem evidência recente ficam como “Possivelmente encerrada”, visíveis no radar. A rotina no GitHub fará novas tentativas. Isso não é uma afirmação de que todas as vagas fecharam.

A publicação via `deploy-pages.yml` usa o ambiente `github-pages` e reage também à conclusão da coleta. Se o GitHub exigir, selecionar **GitHub Actions** em Settings → Pages → Source. Isso evita que commits do bot deixem a versão pública desatualizada.

## Ativar Vercel + Supabase

1. Criar ou selecionar um projeto Supabase dedicado e executar `supabase/schema.sql` uma vez. O script usa `auth.users`; cria políticas RLS e as funções transacionais.
2. Criar o usuário proprietário em Supabase Authentication. Para uso pessoal, desabilitar novos cadastros públicos. A interface usa login por e-mail/senha de usuário já provisionado.
3. Importar este repositório na Vercel, com framework **Other**. `vercel.json` constrói `dist` e detecta `api/*.js` como funções. A compilação só copia arquivos públicos; não expõe SQL, testes, segredos ou scripts do servidor.
4. Definir variáveis da Vercel conforme `.env.example`: `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `OWNER_USER_ID`, `GITHUB_TOKEN`, `GITHUB_REPOSITORY`, `ALLOWED_ORIGINS`. `GITHUB_TOKEN` deve ser fine-grained e restrito a este repositório, com Actions read/write. Não incluir token nem `service_role` em `config.js`. `ALLOWED_ORIGINS` precisa conter a origem exata do site (sem barra final e sem caminho).
5. Definir secrets no GitHub Actions: `SUPABASE_URL` e `SUPABASE_SERVICE_ROLE_KEY`. A chave privilegiada só é usada pelo coletor para publicar o catálogo. O backend de perfil usa token do próprio usuário, respeitando RLS.
6. Executar “Atualizar vagas” no GitHub Actions para popular o banco. Reimplantar Vercel com as variáveis configuradas. Na Vercel, `PUBLIC_API_BASE` pode ficar vazio (mesma origem). Para continuar acessando pelo GitHub Pages, preencher `config.js` apenas com URL da Vercel, URL Supabase e chave pública anon; incluir `https://juansenaff.github.io` nas origens permitidas.
7. Entrar em “Minha conta”. Se houver dados na conta e no navegador, a interface oferece exportar o rascunho e escolher qual continuar usando. Testar atualização autenticada e sincronização em dois dispositivos antes de considerar a ativação concluída.

O status da atualização é observado pelo ID/data da execução do workflow. O token GitHub nunca passa pelo navegador. O bloqueio de cinco minutos usa PostgreSQL; não depende de memória de uma função serverless. A coleta continua no GitHub Actions e não fica presa ao tempo de execução HTTP.

## Verificação local

```sh
pip install requests beautifulsoup4
python -m unittest discover -s tests -p 'test_*.py'
node --test tests/*.test.js
python scripts/build_catalog.py
python scripts/build_site.py
```

`build_catalog.py --verify` consulta os anúncios; exige acesso às fontes públicas. `sync_database.py` só publica no Supabase quando suas variáveis estão configuradas. Nunca executar o coletor com credenciais no código.

## Limites explícitos

- Níveis exigidos, estimativas de esforço e score de empresa são heurísticas transparentes; a análise não é uma garantia de contratação.
- Texto não mapeado exige confirmação; revisar o anúncio continua necessário. LinkedIn/Gupy podem restringir consulta pública.
- O histórico de perfil semanal é registrado ao abrir o painel, não por um agendamento que conheça o perfil quando o usuário não acessa. O histórico de mercado é automatizado.
- Alertas são internos ao painel. E-mails, push e mensagens externas não foram ativados.
- Autenticação funciona com uma conta previamente provisionada. Cadastro, recuperação de senha e prova prática automática são evoluções futuras.
- A integração online exige validação real após provisionar os serviços. Os testes atuais verificam regras locais, rotas e proteção básica, não um ambiente Supabase/Vercel em produção.

Referências de implementação: [Vercel Node.js](https://vercel.com/docs/functions/runtimes/node-js), [Supabase RLS](https://supabase.com/docs/guides/database/postgres/row-level-security), [GitHub workflow dispatch](https://docs.github.com/en/rest/actions/workflows#create-a-workflow-dispatch-event).
