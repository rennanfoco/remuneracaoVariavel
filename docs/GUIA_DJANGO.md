# Guia de início rápido — Django

Este é um guia prático de Django, focado no que é usado no [Portal RV](../README.md#portal-web-v2). Não é uma referência completa do framework — é o suficiente para você navegar, entender e mexer neste projeto com confiança.

## 0. Mapa do projeto

O repositório tem duas partes, cada uma **autocontida na sua própria pasta** — nenhuma das duas depende de arquivos fora de si mesma:

```
remuneracaoVariavel/
│
├── motor_calculo/              ⎫  V1 — MOTOR DE CÁLCULO (standalone, via CLI)
│   ├── config.py               ⎪
│   ├── main.py                 ⎪
│   ├── criar_referencias.py    ⎪
│   ├── generate_samples.py     ⎪
│   ├── test_totvs_api.py       ⎪
│   ├── referencias.xlsx        ⎪  regras de negócio (não versionado)
│   ├── data/                   ⎪  entrada/saída da CLI (não versionado)
│   ├── samples/                ⎪  dados de exemplo (não versionado)
│   └── rv/                     ⎬
│       ├── loader.py           ⎪  lê e normaliza os arquivos de entrada
│       ├── eligibility.py      ⎪  regras de elegibilidade/proporcionalidade
│       ├── engine.py           ⎪  orquestra o cálculo do mês
│       ├── output.py           ⎪  gera o TXT e o relatório Excel
│       ├── totvs_client.py     ⎪  cliente da API do TOTVS RM
│       └── calculators/
│           └── calculadora.py  ⎭  calculadora genérica guiada pela planilha
│
├── portal/                     ⎫  V2 — PORTAL DJANGO (standalone, autocontido)
│   ├── manage.py               ⎪
│   ├── db.sqlite3              ⎪  (não versionado)
│   │                           ⎪
│   ├── motor_calculo/          ⎪  ★ CÓPIA PRÓPRIA do motor acima — mesmo
│   │   ├── config.py           ⎪    código, não é a mesma pasta. O portal
│   │   ├── main.py             ⎪    nunca lê nada de fora de portal/. Se
│   │   └── rv/...              ⎪    corrigir um bug de cálculo, replique
│   │                           ⎪    nos dois lugares.
│   │                           ⎪
│   ├── webapp/                 ⎪  PROJETO (configuração global)
│   │   ├── settings.py         ⎪    banco, apps instalados, chaves, idioma
│   │   │                       ⎪    (é aqui que portal/motor_calculo/ entra
│   │   │                       ⎪    no sys.path — ver comentário no arquivo)
│   │   ├── urls.py             ⎪    rotas raiz (/, /admin/, /calculo/, /contas/)
│   │   └── wsgi.py / asgi.py   ⎪    ponte com o servidor web real (gunicorn)
│   │
│   ├── apps/                   ⎪
│   │   ├── regras/             ⎪  REGRAS DE NEGÓCIO (Cargos, Grupos, Faixas...)
│   │   │   ├── models.py       ⎪    as tabelas do banco
│   │   │   ├── admin.py        ⎪    liga os models à tela /admin/
│   │   │   └── management/commands/
│   │   │       ├── importar_referencias.py   xlsx → banco (migração one-time)
│   │   │       └── exportar_referencias.py   banco → xlsx (antes de cada cálculo)
│   │   │
│   │   ├── calculo/            ⎪  RODAR O CÁLCULO (upload, execução, histórico)
│   │   │   ├── models.py       ⎪    ExecucaoCalculo, ArquivoUpload
│   │   │   ├── forms.py        ⎪    valida o formulário da tela
│   │   │   ├── views.py        ⎪    "o que acontece quando clica em Calcular"
│   │   │   ├── services.py     ⎪    ★ chama motor_calculo/main.py via subprocess
│   │   │   ├── urls.py         ⎪    rotas /calculo/...
│   │   │   └── templates/calculo/   executar.html, historico.html, resultado.html
│   │   │
│   │   └── accounts/           ⎪  LOGIN
│   │       ├── middleware.py   ⎪    integração com Azure AD (produção)
│   │       └── management/commands/bootstrap_grupos.py   cria grupo "Gestão RV"
│   │
│   ├── templates/               layout compartilhado por todo o site
│   │   ├── base.html              cabeçalho, cores, fontes, a "onda" da marca
│   │   └── accounts/login.html
│   │
│   └── static/                  ⎫
│       ├── fonts/*.woff2        ⎪  fonte Omnes (identidade visual da Foco)
│       └── img/                 ⎭  logo, favicon
│
└── docs/
    ├── ARQUITETURA_V2.md       decisões de arquitetura da V2
    └── GUIA_DJANGO.md          este arquivo
```

**Regra de ouro pra se orientar:** se é sobre *calcular RV* (a lógica em si — DMA, NPS, faixas, percentuais), a resposta está em `rv/` — mas existe em **dois lugares idênticos**: `motor_calculo/rv/` (CLI standalone) e `portal/motor_calculo/rv/` (usado pelo portal). Se é sobre *como alguém acessa isso pela web* (login, upload, tela, histórico, edição de regras), a resposta está em `portal/apps/` ou `portal/webapp/`.

Dentro de `portal/`, o Django e o motor embutido se tocam em dois pontos, ambos documentados com comentário no próprio código:
1. [portal/webapp/settings.py](../portal/webapp/settings.py) adiciona `portal/motor_calculo/` ao `sys.path`, pra `import config` funcionar dentro do processo Django (usado por `importar_referencias`).
2. [portal/apps/calculo/services.py](../portal/apps/calculo/services.py) chama `portal/motor_calculo/main.py` como um processo separado (subprocess) — não como um `import`.

**Trade-off consciente:** ter o motor duplicado (uma cópia em cada pasta) é o preço de cada pasta poder ser implantada/distribuída sozinha, sem depender da outra existir ao lado. O custo é manutenção manual — um bug corrigido em `motor_calculo/rv/` não se propaga sozinho para `portal/motor_calculo/rv/`.

## 1. O que é Django, em uma frase

Django é um framework Python para construir sites: ele já resolve banco de dados, autenticação, formulários, admin e roteamento de URLs, para você não reinventar isso a cada projeto. Você escreve a parte específica do seu negócio (aqui: cálculo de RV); o framework cuida do resto.

## 2. Comandos do dia a dia

Todos rodados de dentro de `portal/` (onde está o `manage.py`):

```bash
python manage.py runserver          # sobe o site em http://localhost:8000
python manage.py migrate            # aplica mudanças de estrutura no banco
python manage.py makemigrations     # gera essas mudanças, depois de editar um model
python manage.py createsuperuser    # cria um usuário com acesso total ao /admin/
python manage.py changepassword <usuario>   # troca a senha de alguém
python manage.py shell              # abre um Python com o projeto já carregado
```

Qualquer comando de terminal específico deste projeto (`importar_referencias`, `exportar_referencias`, `bootstrap_grupos`) também roda assim: `python manage.py <nome_do_comando>`.

## 3. Anatomia de um projeto Django

Um projeto Django é dividido em **project** (configuração global) e **apps** (módulos de funcionalidade). Neste projeto:

```
portal/
  webapp/          ← o project — configuração global
    settings.py       banco de dados, apps instalados, chaves, idioma
    urls.py           rotas raiz

  apps/            ← os apps — cada um cuida de uma parte
    regras/           regras de negócio (Cargos, Grupos, Faixas...)
    calculo/          rodar o cálculo, upload, histórico
    accounts/         autenticação
```

Cada app normalmente tem essa forma por dentro:

| Arquivo | Para que serve |
|---|---|
| `models.py` | as tabelas do banco de dados, como classes Python |
| `admin.py` | liga os models a uma tela de CRUD pronta em `/admin/` |
| `views.py` | funções que recebem uma requisição e devolvem uma resposta |
| `urls.py` | mapeia uma URL para uma view |
| `forms.py` | valida dados vindos de um formulário HTML |
| `templates/<app>/*.html` | o HTML de fato, com dados injetados pela view |
| `migrations/` | histórico versionado de mudanças no banco (gerado automaticamente) |
| `management/commands/*.py` | scripts de terminal específicos do app |

## 4. O ciclo de uma requisição

Quando alguém acessa uma URL do site, a ordem é sempre essa:

```
URL acessada
   ↓
portal/webapp/urls.py           "essa URL começa com /calculo/? manda pro app calculo"
   ↓
portal/apps/calculo/urls.py     "e dentro dele, qual view exatamente?"
   ↓
portal/apps/calculo/views.py    a função roda: lê o banco, processa o formulário, decide o que responder
   ↓
template .html                  a view manda os dados pro HTML, que os exibe
   ↓
resposta enviada ao navegador
```

Middlewares (como o [EasyAuthMiddleware](../portal/apps/accounts/middleware.py)) rodam **antes** da view, em toda requisição — é onde a identidade do usuário é resolvida.

## 5. Models e o ORM (a parte que substitui SQL)

Em vez de escrever SQL, você escreve uma classe Python:

```python
class Cargo(models.Model):
    nome = models.CharField(max_length=120)
    grupo = models.ForeignKey(Grupo, on_delete=models.PROTECT)
    teto = models.DecimalField(max_digits=10, decimal_places=2, null=True)
```

Isso cria (via migration) uma tabela `regras_cargo` com colunas `nome`, `grupo_id`, `teto`. Para consultar:

```python
Cargo.objects.all()                          # todos os cargos
Cargo.objects.filter(grupo__nome="mecanico")  # filtrado
Cargo.objects.get(nome="Motorista")           # um específico
cargo.grupo.modelo                            # segue a relação (join automático)
```

Toda vez que você edita um `models.py`, dois passos:
```bash
python manage.py makemigrations   # "fotografa" a mudança
python manage.py migrate          # aplica no banco de verdade
```

## 6. O admin — CRUD de graça

Este é o "milagre" mais visível do Django. Você não desenhou a tela de `/admin/`: só descreveu a estrutura em `models.py` e registrou em `admin.py`:

```python
@admin.register(Cargo)
class CargoAdmin(admin.ModelAdmin):
    list_display = ["nome", "grupo", "teto"]
    autocomplete_fields = ["grupo"]
```

O Django gera listagem, busca, formulário de edição, validação e paginação sozinho. É por isso que a edição de regras de negócio (Cargos, Grupos, Faixas) não precisou de nenhuma tela feita à mão — está tudo em [portal/apps/regras/admin.py](../portal/apps/regras/admin.py).

## 7. Templates — a linguagem dentro do HTML

Django Templates usam `{{ variavel }}` para imprimir e `{% tag %}` para lógica:

```html
{% extends "base.html" %}     {# herda o layout comum #}
{% block content %}
  <h1>{{ execucao.competencia }}</h1>
  {% if execucao.status == "concluido" %}
    <p class="sucesso">Pronto!</p>
  {% endif %}
  {% for arquivo in execucao.arquivos.all %}
    <li>{{ arquivo.tipo }}</li>
  {% endfor %}
{% endblock %}
```

`{% extends %}` + `{% block %}` é como este projeto evita repetir o cabeçalho/rodapé em toda página — veja [portal/templates/base.html](../portal/templates/base.html) e como as outras templates "herdam" dele.

## 8. Forms — validação de dados de entrada

```python
class ExecutarCalculoForm(forms.Form):
    competencia = forms.CharField(max_length=7)

    def clean_competencia(self):
        valor = self.cleaned_data["competencia"]
        if not COMPETENCIA_RE.match(valor):
            raise forms.ValidationError("Formato inválido.")
        return valor
```

A view só precisa chamar `form.is_valid()` — toda a validação (obrigatoriedade, formato, mensagens de erro) já vem pronta. Veja [portal/apps/calculo/forms.py](../portal/apps/calculo/forms.py).

## 9. Onde cada coisa deste projeto mora

| Quero entender... | Vou em... |
|---|---|
| A lógica de cálculo em si (DMA, NPS, faixas...) | [motor_calculo/rv/](../motor_calculo/rv/) |
| Como os dados de regras são estruturados no banco | [portal/apps/regras/models.py](../portal/apps/regras/models.py) |
| Como o cálculo é disparado ao clicar "Calcular" | [portal/apps/calculo/services.py](../portal/apps/calculo/services.py) |
| Como o login funciona (local e Azure AD) | [portal/apps/accounts/middleware.py](../portal/apps/accounts/middleware.py) |
| Configuração geral (banco, apps instalados) | [portal/webapp/settings.py](../portal/webapp/settings.py) |
| O visual das páginas | [portal/templates/base.html](../portal/templates/base.html) |
| Decisões de arquitetura da V2 | [docs/ARQUITETURA_V2.md](ARQUITETURA_V2.md) |

## 10. Erros comuns e o que fazer

| Mensagem | O que costuma ser |
|---|---|
| `OperationalError: no such table` | Esqueceu de rodar `python manage.py migrate` |
| `TemplateDoesNotExist` | Nome/caminho do arquivo `.html` errado, ou app sem `templates/<nome_do_app>/` |
| `NoReverseMatch` | Um `{% url 'nome' %}` no template não bate com nenhuma rota em `urls.py` |
| Mudou o `models.py` e nada aconteceu | Faltou `makemigrations` **e** `migrate` — os dois, nessa ordem |
| Porta 8000 já em uso | Outro `runserver` ainda rodando; feche o terminal antigo ou mate o processo |

## 11. Para ir além

- [Documentação oficial (em inglês)](https://docs.djangoproject.com/) — a referência mais confiável, sempre.
- O melhor jeito de aprender daqui pra frente: abra um arquivo da lista da seção 9, leia de cima a baixo, e me pergunte qualquer trecho que não fizer sentido.
