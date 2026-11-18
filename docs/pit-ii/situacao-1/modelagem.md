# Modelagem UML do BANCO 2027

Os diagramas descrevem o recorte de consulta e as fronteiras do sistema. Os nomes das classes representam conceitos de domínio.

## Casos de uso

```mermaid
flowchart LR
    V["Visitante"] --> R(["Consultar Radar"])
    V --> F(["Buscar e filtrar vagas"])
    V --> D(["Abrir detalhe"])
    V --> FAV(["Gerenciar favoritos locais"])
    V --> C(["Comparar vagas"])
    U["Usuário autenticado"] --> S(["Sincronizar estado pessoal"])
    A["Operador autorizado"] --> G(["Solicitar atualização da coleta"])
    G --> H["GitHub Actions"]
```

## Diagrama de classes do domínio

```mermaid
classDiagram
    class Empresa {
        +String nome
        +String dominio
    }
    class Vaga {
        +String chave
        +String cargo
        +String estado
    }
    class Requisito {
        +String texto
        +String tipo
        +Boolean obrigatorio
        +Integer posicao
    }
    class FonteDaVaga {
        +String url
        +DateTime ultimaVerificacao
    }
    class Perfil {
        +UUID usuario
        +DateTime atualizacao
    }
    class Habilidade {
        +String identificador
        +Integer nivel
        +Integer evidencia
    }
    class Candidatura {
        +String chaveVaga
        +String etapa
    }
    Empresa "0..1" --> "0..*" Vaga : anuncia
    Vaga "1" *-- "0..*" Requisito : possui
    Vaga "1" *-- "0..*" FonteDaVaga : registra
    Perfil "1" *-- "0..*" Habilidade : registra
    Perfil "1" *-- "0..*" Candidatura : acompanha
    Candidatura ..> Vaga : referencia por chave
```

O mapa de persistência relaciona Empresa a `companies`, Vaga a `jobs`, Requisito a `job_requirements` e FonteDaVaga a `job_sources`. Perfil é representado por `user_state` e pelas projeções `skills` e `applications`. A ligação de candidatura com vaga é conceitual. A coluna `applications.job_key` faz a associação por chave no código.

## Diagrama de sequência da consulta

```mermaid
sequenceDiagram
    actor V as Visitante
    participant UI as Interface web
    participant J as Catálogo publicado
    participant API as API Vercel
    participant DB as PostgreSQL
    V->>UI: Abre o Radar
    UI->>J: Lê a cópia jobs.json
    opt Integração configurada
        UI->>API: GET /api/jobs
        API->>DB: Consulta catálogo e metadados
        alt Resposta válida
            DB-->>API: Vagas e metadados
            API-->>UI: JSON atualizado
        else API indisponível
            API-->>UI: Falha de consulta
            UI->>UI: Mantém a cópia e mostra aviso
        end
    end
    V->>UI: Digita termo ou muda filtro
    UI->>UI: Filtra o catálogo em memória
    UI-->>V: Atualiza a lista ou mostra estado vazio
```

## Diagrama de atividades da comparação

```mermaid
flowchart TD
    I([Início]) --> R[Abrir Radar de vagas]
    R --> M[Marcar vagas para comparação]
    M --> D{Há de duas a três vagas selecionadas?}
    D -->|Sim| C[Abrir Comparar exigências]
    D -->|Não| M
    C --> E[Examinar exigências lado a lado]
    E --> F([Fim])
```

## Implementação de referência

| Responsabilidade | Arquivos |
|---|---|
| Visualização, eventos e rotas da interface | [index.html](../../../index.html), [styles.css](../../../styles.css) e [app.js](../../../app.js) |
| Regras de aderência e priorização | [engine.js](../../../engine.js) |
| Rotas HTTP e acesso a serviços | [jobs.js](../../../api/jobs.js), [state.js](../../../api/state.js) e [server.js](../../../lib/server.js) |
| Coleta e publicação do catálogo | [update_vagas.py](../../../scripts/update_vagas.py) e [sync_database.py](../../../scripts/sync_database.py) |
| Persistência | [schema.sql](../../../supabase/schema.sql) |
