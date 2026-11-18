# Escopo e requisitos do BANCO 2027

O BANCO 2027 reúne anúncios dispersos e apresenta requisitos, filtros e prioridades em um só painel. Atende estudantes e profissionais em início de carreira que buscam oportunidades de tecnologia, principalmente em bancos e fintechs. A coleta considera São Paulo e trabalho remoto no Brasil e inclui Microsoft e Google como exceções explicitadas no [README do projeto](../../../README.md).

## Recorte da atividade

A entrega cobre o painel, o Radar de vagas, o detalhe de uma vaga, os favoritos e a comparação de até três oportunidades. O perfil, a fila de ação, o plano de estudo, as candidaturas e os históricos fazem parte do projeto e ajudam a explicar a arquitetura. O recorte público pode ser demonstrado com o rascunho local do navegador. A sincronização pessoal e o disparo da coleta possuem condições próprias de acesso.

## Requisitos funcionais

| ID | Requisito | Critério de aceite |
|---|---|---|
| RF01 | Consultar o catálogo publicado | Abrir o Radar e listar vagas com empresa, cargo e estado do anúncio. |
| RF02 | Buscar e filtrar | Buscar por texto ou selecionar filtros. A lista e o contador mudam com os critérios. Uma combinação sem resultados exibe uma mensagem de estado vazio. |
| RF03 | Consultar o detalhe | Abrir a vaga por endereço próprio e apresentar requisitos obrigatórios, diferenciais e responsabilidades quando disponíveis. |
| RF04 | Favoritar | Marcar ou desmarcar uma vaga e consultar o subconjunto pelo filtro Favoritas. |
| RF05 | Comparar oportunidades | Selecionar até três vagas e apresentar as exigências lado a lado. |
| RF06 | Acompanhar a evolução | Mostrar os registros de compatibilidade e a variação da procura por tecnologias, conforme o período selecionado e a disponibilidade de registros históricos. |
| RF07 | Salvar o estado pessoal | Manter o rascunho no navegador e permitir sincronização para a conta autenticada quando a integração estiver disponível. |

## Requisitos não funcionais

| ID | Requisito | Critério de aceite |
|---|---|---|
| RNF01 | Continuidade da consulta | Exibir a última cópia publicada do catálogo se a API de vagas estiver indisponível e comunicar o modo alternativo. |
| RNF02 | Proteção dos dados pessoais | Associar o estado à conta autenticada. Aplicar a política de acesso por proprietário no PostgreSQL. |
| RNF03 | Rastreabilidade do catálogo | Preservar URL, fonte e estado da vaga publicada. Identificar dados pendentes de verificação. |
| RNF04 | Interface responsiva | Permitir navegação nos fluxos do radar e do detalhe com controles rotulados e layout adaptável. |
| RNF05 | Integridade | Usar chaves e restrições no banco. Gravar o estado da conta e suas projeções na mesma transação. |

## Revisão do planejamento

O recorte da entrega foi limitado aos fluxos que podem ser avaliados na aplicação publicada. A documentação identifica as fronteiras entre interface, regras de aderência, API, coleta e armazenamento. O [fluxo de interface](interface.md) registra os estados de erro e os pontos conhecidos para reteste. O [projeto de dados](banco-de-dados.md) relaciona as entidades conceituais ao esquema versionado.
