# Automação de Remuneração Variável (RV)

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
| `Cargos` | Mapeia cada cargo (nome exato do TOTVS) ao seu grupo de cálculo |
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
| `dma-accumulated*.csv` | Coral | CSV `;` |
| `data*.xlsx` | Power BI (NPS por loja) | Excel |
| `Preventivas*.xlsx` | Frotas (aba "Análise de Preventivas") | Excel |
| `Fechamento*.xlsx` | Frotas (Bate Pátio) | Excel |
| `Nonrev*.xlsx` | Frotas | Excel |
| `Importação Planilha*.csv` | Coral (meta de faturamento) | CSV `;` |
| `Lista de Logins*.xlsx` | Analista (mapeamento login → matrícula) | Excel |

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

## Portal Web (V2)

Além da CLI, o projeto tem um portal Django (pasta [`portal/`](portal/)) com login, upload de arquivos e edição de regras de negócio pela tela em vez de editar o `referencias.xlsx` diretamente.

`portal/` é **autocontido**: tem sua própria cópia do motor de cálculo em `portal/motor_calculo/` (mesmo código de `motor_calculo/` na raiz, reaproveitado sem alteração de lógica — não é a mesma pasta, é uma cópia, pra o portal não depender de nada fora de si mesmo). Se corrigir um bug de cálculo, replique a correção nos dois lugares.

**Como funciona:** as regras de negócio (Cargos, Grupos, Regras_Calculo, Tetos, Metas_Mensais) ficam no banco de dados (app `regras`), editáveis pelo Django admin. Ao rodar um cálculo (app `calculo`), o portal exporta o estado atual do banco para um `referencias.xlsx` temporário e chama `portal/motor_calculo/main.py` via subprocess — a mesma CLI de sempre, sem nenhuma alteração no motor.

### Rodando localmente

```bash
pip install -r requirements.txt          # já inclui Django e dependências do portal

cd portal
python manage.py migrate                  # cria o banco local (SQLite)
python manage.py importar_referencias --arquivo motor_calculo/referencias.xlsx   # migração one-time
python manage.py bootstrap_grupos          # cria o grupo de permissão "Gestao RV"
python manage.py createsuperuser

python manage.py runserver
```

Acesse `http://localhost:8000` — login normal do Django em desenvolvimento (em produção, autenticação via Azure AD/Easy Auth, ver `apps/accounts/middleware.py`).

| Rota | O que faz |
|---|---|
| `/calculo/` | Rodar cálculo: competência, upload dos 7 arquivos (ou API do TOTVS), download do TXT/relatório |
| `/calculo/historico/` | Histórico de execuções — auditoria de quem rodou o quê e quando |
| `/admin/` | Edição de regras de negócio (Cargos, Grupos, Regras_Calculo, Tetos, Metas_Mensais), com histórico de alterações |

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
