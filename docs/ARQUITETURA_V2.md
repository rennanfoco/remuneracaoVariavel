# V2 — Portal Web para Cálculo de Remuneração Variável

## Contexto

A V1 era 100% CLI: só quem tem o código Python instalado localmente, sabe rodar `python main.py --competencia AAAA-MM` e tem acesso ao `referencias.xlsx` consegue apurar a RV. Isso concentra a operação em uma pessoa e torna qualquer edição de regra de negócio (cargos, faixas, tetos, metas mensais) dependente de abrir e editar um arquivo Excel manualmente, sem controle de acesso, trilha de auditoria ou validação estrutural.

A V2 transforma isso num portal web interno, acessível por qualquer colaborador autorizado na rede da empresa via navegador, sem precisar do código localmente, com:
1. Login corporativo (a empresa usa **Microsoft 365 / Azure AD**)
2. Tela intuitiva para rodar o cálculo mensal (upload dos arquivos, selecionar competência, calcular, baixar resultados) — usada mensalmente por mais gente
3. Telas para editar as regras de negócio (Cargos, Grupos, Regras_Calculo, Tetos, Metas_Mensais) sem abrir o Excel — usada raramente, por 1-2 pessoas de RH/Gestão RV
4. Trilha de auditoria (quem rodou o quê, quem editou qual regra) — relevante por lidar com dados que afetam pagamento de salário

Duas arquiteturas foram avaliadas em profundidade (Streamlit vs. Django). Decisão: **Django**.

## Por que Django (e não Streamlit)

- O requisito 3 (editar regras) é fundamentalmente CRUD relacional com integridade referencial: todo grupo em `Regras_Calculo` precisa existir em `Grupos`; todo cargo de grupo `teto_fixo` precisa de teto; faixas duplicadas `(grupo, indicador, faixa)` são inválidas. O **Django admin + ORM resolve isso estruturalmente** (foreign keys, `unique_together`, `clean()`) em vez de depender de checagens manuais como antes (`_grupos_sem_modelo` em `config.py`, que só disparava em runtime). O equivalente em Streamlit (`st.data_editor`) não tem integridade referencial, lock de concorrência nem auditoria nativos.
- Azure AD → **Azure App Service com Easy Auth** resolve hospedagem e SSO corporativo na mesma peça de infra, sem escrever código de autenticação.
- Auditoria (`django-simple-history`) e permissões por grupo (`django.contrib.auth` nativo) vêm essencialmente de graça.
- O motor de cálculo (`rv/engine.py`, `rv/calculators/calculadora.py`, `rv/eligibility.py`, `rv/output.py`, `rv/loader.py`) e a CLI (`main.py`) **não precisam de nenhuma alteração de lógica** — são chamados via `subprocess`, contornando um problema real: `config.py` carrega as regras como constantes fixas no import, então um processo web de longa duração não veria edições de regra feitas pela UI sem reiniciar. Rodar `main.py` como subprocesso cria um processo Python novo a cada cálculo — import sempre fresco.

## Arquitetura implementada

```
remuneracaoVariavel/
  motor_calculo/                  # V1 — PACOTE LEGADO, standalone, zero alterações de lógica
    rv/
    config.py                     # 1 mudança mínima: _REF aceita override via REFERENCIAS_XLSX_PATH
    main.py

  portal/                         # V2 — o Django, AUTOCONTIDO (não depende de nada fora daqui)
    manage.py
    motor_calculo/                 # ★ cópia própria do motor acima — mesmo código,
      rv/                            duplicado de propósito, não uma referência.
      config.py                      Ver "Autocontenção" abaixo.
      main.py                        # chamado via subprocess por portal/apps/calculo/services.py
    webapp/                        # settings do Django
      settings.py  urls.py  wsgi.py   # settings.py põe portal/motor_calculo/ no sys.path
    apps/
      regras/                      # Grupo, Cargo, IndicadorRegra, FaixaCalculo, MetaMensal, ParametroTOTVS
        models.py  admin.py
        management/commands/importar_referencias.py   # migração one-time do xlsx → banco
        management/commands/exportar_referencias.py    # banco → xlsx (para subprocess e backup)
      calculo/                     # ExecucaoCalculo, ArquivoUpload
        models.py  forms.py  views.py  services.py  urls.py
        templates/calculo/
      accounts/                    # middleware.py (Easy Auth) + bootstrap_grupos
```

> Nota: `motor_calculo/` e `portal/` eram uma pasta única (a raiz do repositório) durante a implementação inicial da V2, depois foram separados fisicamente (ver [GUIA_DJANGO.md](GUIA_DJANGO.md#0-mapa-do-projeto)), e por fim o motor foi duplicado para dentro de `portal/` — ver "Autocontenção" logo abaixo.

### Autocontenção

Cada pasta (`motor_calculo/` e `portal/`) é **autossuficiente**: nenhuma lê ou importa nada de fora de si mesma. Isso significa que `portal/` pode ser implantado sozinho (ex: só essa subpasta enviada pro Azure App Service) sem quebrar — ele nunca depende de um `motor_calculo/` irmão existir no disco de produção.

O custo desse trade-off é duplicação: `portal/motor_calculo/` é uma cópia literal de `motor_calculo/` na raiz, não um link nem um pacote instalado. **Se um bug de cálculo for corrigido em um lado, precisa ser replicado manualmente no outro** — não há sincronização automática. Isso é aceitável enquanto o motor muda pouco (é código estável, testado); se voltar a mudar com frequência, vale revisitar essa decisão (ex: publicar `motor_calculo/` como um pacote Python instalável via `pip install -e`, uma dependência de verdade em vez de uma cópia).

### Modelagem (`portal/apps/regras/models.py`)

Espelha a estrutura que `config._parse_regras`/`_parse_metas` já produzem, normalizada em 2 níveis (indicador → faixas), não a tabela "longa" do Excel 1:1:

- `Grupo(nome, modelo)` — `modelo` tem 3 valores: `percentual`, `teto_fixo`, e `desconsiderar` (sentinela para cargos sem RV — ver "Detalhes descobertos na implementação")
- `Cargo(nome, grupo FK, teto)` — `clean()` exige `teto` quando `grupo.modelo == "teto_fixo"`
- `IndicadorRegra(grupo FK, indicador, direcao, chave_meta)` — `unique_together=(grupo, indicador)`
- `FaixaCalculo(indicador_regra FK, faixa, valor_min, valor_max, pct)` — `unique_together=(indicador_regra, faixa)`. Adicionar uma faixa 3 é uma linha nova pelo admin, nenhum código muda.
- `MetaMensal(mes, chave, faixa, valor_min, valor_max)` — `unique_together=(mes, chave, faixa)`
- `ParametroTOTVS(parametro, valor, descricao)`

`portal/apps/calculo/models.py`: `ExecucaoCalculo` (competência, status, quem rodou, log, arquivos gerados) e `ArquivoUpload` (tipo espelha `rv.loader.PADROES`).

### Fluxo de execução (`portal/apps/calculo/services.py`)

1. `exportar_referencias` materializa as regras atuais do banco num `referencias.xlsx` temporário (um por execução — evita concorrência entre execuções simultâneas).
2. Copia os arquivos enviados para um diretório temporário, renomeados para o nome canônico que `rv.loader.PADROES` espera via glob.
3. `subprocess.run([python, "motor_calculo/main.py", "--competencia", comp, "--input", tmp_in, "--output", tmp_out], cwd=motor_calculo/, env={"REFERENCIAS_XLSX_PATH": tmp_referencias, ...})`.
4. Sucesso → anexa TXT/relatório ao `ExecucaoCalculo`. Falha → grava stderr em `erro_mensagem`.

Síncrono (sem Celery) — suficiente para o volume (~660 linhas, segundos de processamento).

### Autenticação

Produção: Azure App Service **Easy Auth** — autentica na borda contra o Azure AD do tenant da empresa, injeta a identidade via header. `portal/apps/accounts/middleware.py::EasyAuthMiddleware` lê esse header e resolve/cria o `User` Django correspondente. Sem esse header (dev local), o middleware não faz nada e o login normal do Django assume.

Autorização: grupo Django "Gestão RV" (`settings.GRUPO_GESTAO_RV`, criado por `python manage.py bootstrap_grupos`) com permissão de editar `apps.regras`.

### Hospedagem (pendente de provisionamento)

Azure App Service (Python) + Azure Database for PostgreSQL — dado que o tenant Azure AD já existe. Precisa confirmar com a TI da empresa se há assinatura Azure ativa com permissão de criar recursos.

## Detalhes descobertos na implementação

- **`config.py` precisou de 1 linha nova** (não estava no plano original): o caminho do `referencias.xlsx` era hardcoded relativo à localização de `config.py`. Sem um jeito de sobrescrever isso, o subprocess do portal teria que escrever no `referencias.xlsx` real do projeto a cada cálculo — risco de concorrência entre execuções simultâneas. Adicionada a variável de ambiente opcional `REFERENCIAS_XLSX_PATH`; sem ela, comportamento 100% idêntico ao anterior.
- **Sentinela `desconsiderar`**: 11 cargos no `referencias.xlsx` real usam `grupo_calculo = "desconsiderar"` (cargos administrativos sem RV) — um valor que nunca existiu na aba `Grupos` (só na aba `Cargos`), porque `config.py` nunca exigiu isso (só valida grupos que aparecem em `Regras_Calculo`). O model `Cargo.grupo` é uma FK obrigatória, então esses 11 cargos precisaram de um `Grupo(nome="desconsiderar")` correspondente — adicionado como terceiro valor de `modelo`, que `config.py` (lado legado) ignora ao reexportar, preservando o comportamento original.
- **Validação do round-trip**: `importar_referencias` seguido de `exportar_referencias` sobre o `referencias.xlsx` real produz `REGRAS`, `TETOS`, `METAS_MENSAIS` e `_TOTVS` **idênticos** (comparação de dicts) aos carregados diretamente do arquivo original. A única diferença é uma linha de instrução do próprio template do Excel sendo ignorada (já era ruído inofensivo no sistema original).
- **Teste ponta a ponta**: executado localmente com os arquivos reais de `motor_calculo/data/input/` (competência 2026-05) via `portal/apps/calculo/services.executar_calculo()`, usando a cópia interna `portal/motor_calculo/` — concluiu com sucesso, gerando TXT e relatório com valores no mesmo intervalo dos calculados pela CLI na mesma sessão (pequenas variações vêm de dados ao vivo da API do TOTVS RM mudando entre execuções, não de diferença de lógica).

## Fases

1. **Fase 0 — Spike de infra:** ✅ projeto Django local funcionando (SQLite, login local). ⏳ Provisionar App Service + Postgres + Easy Auth em ambiente real — depende de acesso/decisão da TI da empresa.
2. **Fase 1 — Executar e baixar:** ✅ implementado e testado localmente ponta a ponta.
3. **Fase 2 — Editar regras:** ✅ implementado — admin com inlines de faixas, ação "duplicar mês anterior" em Metas Mensais, histórico de alterações.
4. **Fase 3 — Produção:** pendente — logging mais completo nas views, política de retenção dos uploads (contêm salário — decisão de negócio), backup agendado do banco em produção.
5. **Fase 4 (opcional):** Celery+Redis só se o síncrono se mostrar lento na prática.

## Como rodar localmente

Ver seção "Portal Web (V2)" no [README.md](../README.md).
