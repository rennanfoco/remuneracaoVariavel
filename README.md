# Automação de Remuneração Variável (RV)

[![CI](https://github.com/rennanfoco/remuneracaoVariavel/actions/workflows/ci.yml/badge.svg)](https://github.com/rennanfoco/remuneracaoVariavel/actions/workflows/ci.yml)

Sistema que automatiza o cálculo mensal de Remuneração Variável, substituindo um processo manual que levava cerca de 3 dias úteis por competência. Integra dados do TOTVS RM, Coral, Power BI e da área de Frotas, aplica as regras de premiação vigentes por grupo de cargo e gera o arquivo de importação para a folha de pagamento no TOTVS RM, além de um relatório detalhado para validação.

O repositório tem duas partes, cada uma **autocontida na sua própria pasta** — nenhuma depende de arquivos fora dela:

- **[`motor_calculo/`](motor_calculo/)** — o motor de cálculo (V1), usado por linha de comando. Descrito nas seções abaixo.
- **[`portal/`](portal/)** — o portal web (V2), com login e telas. Tem sua própria cópia do motor em `portal/motor_calculo/` (não referencia a pasta acima) — descrito em [Portal Web (V2)](#portal-web-v2).

Veja o mapa completo em [docs/GUIA_DJANGO.md](docs/GUIA_DJANGO.md#0-mapa-do-projeto).

## Pré-requisitos

- Python 3.10 ou superior
- Acesso à API do TOTVS RM (ou, para testes, os arquivos de exemplo em `samples/`)

## Instalação

```bash
git clone <url-do-repositorio>
cd remuneracaoVariavel

python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # Linux/Mac

pip install -r requirements.txt

cd motor_calculo   # os comandos da seção "Uso" abaixo rodam daqui
```

## Configuração

### 1. Credenciais da API (`.env`)

Copie o arquivo de exemplo e preencha com as credenciais reais:

```bash
cp .env.example .env
```

```
TOTVS_RM_BASE_URL=https://SEU-TENANT.rm.cloudtotvs.com.br:PORTA
TOTVS_RM_USERNAME=usuario_de_integracao
TOTVS_RM_PASSWORD=senha_de_integracao
```

O `.env` nunca deve ser commitado — já está no `.gitignore`.

### 2. Regras de negócio (`referencias.xlsx`)

Todas as regras de cálculo (cargos, faixas de atingimento, percentuais, tetos, metas mensais) ficam centralizadas nesse arquivo, que **não é versionado** (contém dados reais de negócio). Para criar a partir do zero:

```bash
python criar_referencias.py
```

Isso gera um `referencias.xlsx` com a estrutura esperada, pronto para ser preenchido/ajustado. Um template com instruções para o time interno também está disponível em `referencias_template.xlsx`.

Abas do arquivo:

| Aba | Conteúdo |
|---|---|
| `Cargos` | Mapeia cada cargo (nome exato do TOTVS) ao seu grupo de cálculo. **Cargo que não estiver aqui não é calculado**: não há parâmetros definidos para ele, então ele fica de fora do TXT e aparece como aviso e na aba "Não calculados" do relatório |
| `Grupos` | Define, por grupo, se a base do prêmio é o salário (`percentual`) ou um teto fixo em R$ (`teto_fixo`) |
| `Regras_Calculo` | Faixas de atingimento e percentuais de prêmio por grupo e indicador |
| `Tetos` | Valor máximo de prêmio em R$ para os grupos de teto fixo |
| `Metas_Mensais` | Metas de NPS e NONREV, atualizadas mês a mês |
| `TOTVS` | Código do evento de RV na folha, código da coligada e parâmetros técnicos |

`Regras_Calculo` e `Metas_Mensais` usam formato **longo**: uma linha por faixa (coluna `faixa` com o número — maior número = melhor faixa), em vez de uma coluna por faixa. Isso permite qualquer quantidade de faixas por indicador: para adicionar uma faixa 3, basta adicionar uma linha na planilha, sem alterar código.

`valor_min` e `valor_max` são **ambos inclusivos** (intervalo fechado). Ao configurar faixas adjacentes, garanta que não haja vão entre elas — ex: faixa 1 = `76` a `78` e faixa 2 = `79` sem máximo cobrem todos os valores a partir de 76 sem lacuna; se a faixa 2 come­çasse em `80`, um valor igual a `79` não bateria em nenhuma das duas.

O sistema valida essa planilha no carregamento: se um grupo tiver regras sem modelo de cálculo definido, ou se faltar meta para a competência rodada, o processamento é interrompido com uma mensagem indicando o que precisa ser corrigido.

## Uso

### Cálculo com dados reais (via API do TOTVS RM)

```bash
python main.py --competencia 2026-05 --api
```

Se o arquivo `colaboradores_rm.csv` não existir em `data/input/`, o sistema busca os colaboradores automaticamente pela API — não é necessário passar `--api` explicitamente nesse caso.

### Cálculo com dados de exemplo (para testes)

```bash
python generate_samples.py          # gera arquivos de exemplo em samples/
python main.py --competencia 2026-05 --sample
```

### Outras opções

```bash
python main.py --competencia 2026-05 --input data/input --output data/output
```

| Flag | Descrição |
|---|---|
| `--competencia` | Obrigatório. Formato `AAAA-MM` |
| `--input` | Diretório com os arquivos de entrada (padrão: `data/input`) |
| `--output` | Diretório para os arquivos gerados (padrão: `data/output`) |
| `--sample` | Usa os arquivos de exemplo em `samples/` |
| `--api` | Força a busca de colaboradores via API do TOTVS RM |

## Arquivos de entrada esperados

| Arquivo | Origem | Formato |
|---|---|---|
| `colaboradores_rm.csv` (ou API) | TOTVS RM | CSV `;` |
| `dma-pro-rata*.csv` | Coral, rateado por dia dentro do mês (pro rata) | CSV |
| `data*.xlsx` | Power BI (NPS por loja) | Excel |
| `Preventivas*.xlsx` | Frotas (aba "Análise de Preventivas") | Excel |
| `Fechamento*.xlsx` | Frotas (Bate Pátio) | Excel |
| `Nonrev*.xlsx` | Frotas | Excel |
| `Base metas*.xlsx` | Controladoria (meta de faturamento por login) | Excel — aba com `Login`, `Centro de Custo`, `DMA` e `Valor` |
| `Lista de Logins*.xlsx` | Analista (mapeamento login → matrícula) | Excel |

Os formatos antigos continuam aceitos: `dma-accumulated*.csv` (Coral por fechamento) no lugar do pro rata e `Importação Planilha*.csv` no lugar do `Base metas`. Se os dois formatos do Coral estiverem na pasta, vale o pro rata.

### Faturamento, meta e atingimento (pro rata)

- **Faturamento** = soma de `VALOR_VENDIDO_PRO_RATA` por login. O arquivo já rateia cada contrato por dia: cada mês recebe só a parte dos dias que caem nele, inclusive de contratos ainda abertos. Para a loja, o faturamento conta na loja onde a venda foi feita.
- **Meta** vem do `Base metas` (coluna `Valor`, sem arredondar) e é **proporcional aos dias trabalhados** no mês: dias do RM ÷ 30, mês cheio = 30. Quem trabalhou 15 dias tem metade da meta. Sem dado de dias, vale a meta cheia.
- **Atingimento da pessoa** = faturamento ÷ meta proporcional. **Atingimento da loja** = faturamento da loja ÷ soma das metas proporcionais dos atendentes dela (a loja de cada meta é a da própria planilha, então quem tem meta e não vendeu nada no mês continua contando).
- A meta da **regional** continua sendo o valor fixo da aba `Metas_Faturamento_Regional` do `referencias.xlsx`.
- O prêmio continua proporcional aos dias trabalhados no final do cálculo (`rv/eligibility.py`).
- Se o arquivo do Coral tiver contratos fora do mês da competência, o cálculo avisa (não bloqueia).

## Saídas geradas

- `rv_<competencia>.txt` — arquivo de importação para a folha no TOTVS RM
- `rv_<competencia>_relatorio.xlsx` — relatório detalhado por colaborador (valor de cada indicador, multiplicador aplicado, prêmio final) e resumo por grupo, para validação antes do fechamento

## Estrutura do projeto

```
motor_calculo/
  main.py                    # ponto de entrada (CLI)
  config.py                  # carrega os parâmetros do referencias.xlsx
  criar_referencias.py       # gera o referencias.xlsx base
  generate_samples.py        # gera dados de exemplo em samples/
  test_totvs_api.py          # diagnóstico de conexão com a API do TOTVS RM
  referencias.xlsx           # regras de negócio (não versionado)
  data/                      # arquivos de entrada/saída (não versionado)
  samples/                   # dados de exemplo (não versionado)
  rv/
    loader.py                # leitura e normalização dos arquivos de entrada
    eligibility.py           # regras de elegibilidade e proporcionalidade
    engine.py                # orquestrador do cálculo
    output.py                # geração do TXT e do relatório Excel
    totvs_client.py          # cliente da API do TOTVS RM
    calculators/
      calculadora.py         # calculadora genérica guiada pelas regras da planilha
```

## Ferramentas auxiliares

- `python test_totvs_api.py --mes 05 --ano 2026` — testa a conexão com a API e imprime o retorno bruto
- `python test_totvs_api.py --mes 05 --ano 2026 --list-cargos` — lista todos os cargos distintos retornados pela API, útil para preencher a aba `Cargos` ao adicionar um cargo novo

## Testes automatizados

O motor de cálculo (`rv/calculators/calculadora.py`, `rv/eligibility.py`, `rv/engine.py`) tem uma suíte de testes unitários que não depende do `referencias.xlsx` real nem de arquivos de entrada — cada teste monta seu próprio cenário controlado. Roda a partir da raiz do repositório:

```bash
python -m unittest discover -t motor_calculo -s motor_calculo/tests -p "test_*.py" -v
```

Como `portal/motor_calculo/` é uma cópia própria do motor (ver [Portal Web (V2)](#portal-web-v2)), a mesma suíte é replicada em `portal/motor_calculo/tests/` e roda contra essa cópia com o mesmo comando (trocando `motor_calculo` por `portal/motor_calculo`). Isso também funciona como alarme de sincronia: se uma correção for feita só de um lado, os testes falham para a cópia que ficou desatualizada.

O CI (GitHub Actions, [`.github/workflows/ci.yml`](.github/workflows/ci.yml)) roda essa suíte contra as duas cópias, mais os testes do portal (abaixo), a cada push/PR na `main`.

## Portal Web (V2)

Além da CLI, o projeto tem um portal Django (pasta [`portal/`](portal/)) com login, upload de arquivos e edição de regras de negócio pela tela em vez de editar o `referencias.xlsx` diretamente.

`portal/` é **autocontido**: tem sua própria cópia do motor de cálculo em `portal/motor_calculo/` (mesmo código de `motor_calculo/` na raiz, reaproveitado sem alteração de lógica — não é a mesma pasta, é uma cópia, pra o portal não depender de nada fora de si mesmo). Se corrigir um bug de cálculo, replique a correção nos dois lugares.

**Como funciona:** as regras de negócio (Cargos, Grupos, Regras_Calculo, Tetos, Metas_Mensais) ficam no banco de dados (app `regras`), editáveis pelo Django admin. Ao rodar um cálculo (app `calculo`), o portal exporta o estado atual do banco para um `referencias.xlsx` temporário e chama `portal/motor_calculo/main.py` via subprocess — a mesma CLI de sempre, sem nenhuma alteração no motor.

### Rodando localmente

```bash
python -m venv venv
venv\Scripts\activate                    # Windows  (Linux/Mac: source venv/bin/activate)
pip install -r requirements.txt          # já inclui Django e dependências do portal

cd portal
python manage.py migrate                  # cria o banco local (SQLite)
python motor_calculo/criar_referencias.py # cria o referencias.xlsx base (não é versionado, ver "Regras de negócio")
python manage.py importar_referencias --arquivo motor_calculo/referencias.xlsx   # carrega as regras no banco
python manage.py bootstrap_grupos          # cria o grupo de permissão "Gestao RV"
python manage.py createsuperuser

python manage.py runserver
```

Acesse `http://localhost:8000` — login normal do Django em desenvolvimento (em produção, autenticação via Azure AD/Easy Auth, ver `apps/accounts/middleware.py`).

Recebeu um `referencias.xlsx` de alguém da equipe (por exemplo, o exportado pelo portal em **Regras → Exportar planilha**)? Pule o `criar_referencias.py` e importe direto, de onde o arquivo estiver:

```bash
python manage.py importar_referencias --arquivo C:/caminho/do/referencias_exportado.xlsx
```

Também dá para importar pela tela (**Regras → Importar planilha**, logado como superusuário ou membro do grupo Gestao RV). O arquivo de regras é o próprio arquivo informado: não precisa existir nenhum `referencias.xlsx` na pasta `motor_calculo/`.

Não precisa de `.env` para rodar o portal localmente: o `runserver` e os testes ligam o modo de desenvolvimento (`DEBUG`) sozinhos. O `.env` (copie de `.env.example`) só é necessário para as credenciais do TOTVS e para mudar o padrão. Em produção, o servidor roda sob gunicorn, onde `DEBUG` vem **desligado** se a variável `DJANGO_DEBUG` não for definida, de propósito.

Se uma página der erro 500 sem mostrar nada no console, rode com `DJANGO_DEBUG=1` para ver o erro completo.

### Testes

```bash
cd portal
python manage.py test apps webapp
```

Cobre permissões das telas (usuário comum x Gestão RV), validação de regra específica por loja, o mecanismo de desfazer/refazer uma importação (`apps/regras/services.py`) e a orquestração de uma execução de cálculo com o subprocess mockado (`apps/calculo/services.py`) — sem depender do motor de cálculo real.

| Rota | O que faz |
|---|---|
| `/calculo/arquivos/` | **Aba Arquivos:** status atual dos arquivos de cada competência; envia/substitui um por vez (validado no envio) |
| `/calculo/` | **Aba Calcular:** calcula a competência com o status atual dos arquivos, sem reenviar nada; opção de buscar colaboradores no TOTVS |
| `/calculo/historico/` | Histórico de execuções — auditoria de quem rodou o quê e quando |
| `/admin/` | Edição de regras de negócio (Cargos, Grupos, Regras_Calculo, Tetos, Metas_Mensais), com histórico de alterações |

### Fluxo mensal no portal

1. **Arquivos** — escolha a competência e envie cada arquivo uma vez. O portal lê o arquivo na hora, com a mesma leitura do cálculo, e recusa o que estiver errado (formato, coluna faltando) ou avisa se parecer de outro mês. Substituir um arquivo guarda a versão anterior.
2. **Calcular** — escolha a competência e calcule. Nada é reenviado: vale a versão mais recente de cada arquivo. Cada cálculo guarda exatamente quais versões usou, então dá para auditar e reproduzir depois.

Regras do status atual:

- **Colaboradores** são sempre **da competência** (dias trabalhados e lista de ativos mudam todo mês). Vêm do TOTVS ("Buscar colaboradores no TOTVS agora", na aba Calcular) ou de um CSV enviado na aba Arquivos, e vale o que aconteceu por último. Sem base da competência e sem marcar a busca, **o cálculo é bloqueado**.
- **Lista de logins** muda pouco: se a competência não tem uma, vale a da competência anterior mais recente (a tela avisa qual).
- Os demais arquivos (Coral, metas, NPS, preventiva, bate pátio) são sempre da própria competência. NONREV é opcional.
- **Cargo sem grupo de cálculo** (não cadastrado na aba Cargos das regras) **não é calculado**. O aviso aparece já no envio da base de colaboradores e, depois do cálculo, na tela de resultado (com a contagem por cargo) e na aba "Não calculados" do relatório. Para incluir essas pessoas, cadastre o cargo em Admin → Cargos e calcule de novo.

### Estrutura

```
portal/
  manage.py
  motor_calculo/                # cópia própria do motor (config.py, main.py, rv/)
  webapp/                       # settings do Django
  apps/
    regras/                     # models + admin das regras de negócio
      management/commands/
        importar_referencias.py    # referencias.xlsx -> banco (migração one-time)
        exportar_referencias.py    # banco -> referencias.xlsx (usado antes de cada cálculo)
    calculo/                    # upload, execução via subprocess, histórico
      services.py                  # exporta regras, roda motor_calculo/main.py via subprocess
    accounts/
      middleware.py                # integração com Azure App Service Easy Auth (produção)
  templates/                    # HTML compartilhado (base.html, login)
  static/                       # fontes, logo, favicon
```

Detalhes de arquitetura, decisões e fases de produção (hospedagem, SSO, auditoria) estão documentados em [docs/ARQUITETURA_V2.md](docs/ARQUITETURA_V2.md). Um guia introdutório de Django aplicado a este projeto está em [docs/GUIA_DJANGO.md](docs/GUIA_DJANGO.md).
