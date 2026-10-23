# Radar de Ações B3 — versão revisada

Aplicativo Streamlit responsivo para celular, com triagem fundamentalista, confirmação de tendência e visualização de cotações.

## O que mudou nesta versão

- Filtro padrão de qualidade: ROE mínimo de 5%, ajustável ou desativável.
- Filtros opcionais para ROIC mínimo, margem EBIT positiva e limite de dívida líquida/patrimônio. Como a interpretação varia por setor, especialmente em bancos e seguradoras, esses filtros setoriais não ficam ativados por padrão.
- Gatilho técnico configurável entre 0% e 20% acima da média móvel simples de 200 pregões.
- Limite de liquidez mais coerente: 2% da média do valor financeiro negociado por dia nos últimos 60 pregões, estimado por fechamento × volume.
- Ranking exibe ROE, ROIC, margens, endividamento e crescimento da receita em cinco anos quando a fonte fornece esses dados.
- Gráfico comparativo usa `Adj Close` quando disponível, para refletir proventos na comparação histórica; a análise da SMA permanece baseada no `Close`.
- A carteira não rotula mais candidatas como ordem de compra e não sugere automaticamente Tesouro Selic/Prefixado quando uma vaga fica vazia.
- O aplicativo informa que não há backtest válido da estratégia, porque os fundamentos disponíveis são atuais e não históricos ponto a ponto.

## Regras atuais de triagem

1. P/L positivo e liquidez mínima em dois meses.
2. Por padrão, ROE igual ou superior a 5%.
3. Cinco rankings preservados: EV/EBIT abaixo de 6; P/VP abaixo de 0,60; dividend yield acima de 5%; PSR abaixo de 0,30; P/L abaixo de 4.
4. Confirmação técnica configurável: cotação igual ou superior à SMA200 mais o percentual escolhido.
5. Limite estimado de volume para cada vaga: valor financeiro médio diário × 2%.
6. Evita escolher papéis com o mesmo radical de quatro caracteres nas vagas da carteira. Isso não garante diversificação entre setores.

## Executar localmente

Requer Python 3.10 ou superior. No terminal, dentro da pasta do projeto:

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
streamlit run streamlit_app.py
```

## Publicar gratuitamente

1. Crie um repositório no GitHub e envie os arquivos desta pasta para a raiz do repositório.
2. Entre no [Streamlit Community Cloud](https://share.streamlit.io/) com a conta do GitHub.
3. Crie um app, escolha o repositório e indique `streamlit_app.py` como arquivo principal.
4. Depois do deploy, abra o link no Safari do iPhone, toque em Compartilhar e escolha Adicionar à Tela de Início.

## Fontes de dados e limitações

- Fundamentos: Fundamentus.
- Cotações e histórico: Yahoo Finance, através da biblioteca `yfinance`.
- Fontes externas podem mudar de estrutura, atrasar, limitar requisições ou ficar indisponíveis.
- Os indicadores fundamentalistas refletem dados atuais disponibilizados pela fonte. Não usar os gráficos como prova de desempenho passado da estratégia: um backtest confiável exigiria fundamentos históricos conhecidos em cada data, universo histórico de ações, regras de rebalanceamento, proventos, custos, impostos e slippage.
- A aproximação por valor financeiro (preço × volume) serve como filtro de liquidez; não garante que uma ordem será executada nesse limite nem evita impacto de mercado em todas as condições.
- O app é uma ferramenta de triagem e pesquisa, não uma recomendação individual de investimento. Valide dados, balanços, riscos e suitability antes de operar.

## Arquivos

- `streamlit_app.py`: aplicação.
- `requirements.txt`: dependências.
- `.streamlit/config.toml`: tema visual.
