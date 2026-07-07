# Automação de Remuneração Variável (RV)

Sistema que automatiza o cálculo mensal de Remuneração Variável, substituindo um processo manual que levava cerca de 3 dias úteis por competência. Integra dados do TOTVS RM, Coral, Power BI e da área de Frotas, aplica as regras de premiação vigentes por grupo de cargo e gera o arquivo de importação para a folha de pagamento no TOTVS RM, além de um relatório detalhado para validação.

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
main.py                    # ponto de entrada (CLI)
config.py                  # carrega os parâmetros do referencias.xlsx
criar_referencias.py       # gera o referencias.xlsx base
generate_samples.py        # gera dados de exemplo em samples/
test_totvs_api.py          # diagnóstico de conexão com a API do TOTVS RM
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
