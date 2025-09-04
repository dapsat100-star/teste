
# Painel OGMP L5 – 12 Sites (Streamlit)

Este app lê um Excel com 12 abas, cada aba representando um site. O layout esperado é:
- Coluna **Parametro** (linhas: `Incerteza`, `Velocidade do Vento`, `Observacoes do Operador`, etc.)
- Colunas **Lat** e **Long** preenchidas na primeira linha da aba
- A partir da coluna **Data**, cada coluna contém **uma data** (na **linha 0**) e **os valores** (nas linhas seguintes)

## Como rodar

```bash
pip install streamlit pandas pydeck altair openpyxl
streamlit run app.py
```

Coloque o arquivo `exemplo banco dados.xlsx` na mesma pasta do `app.py` **ou** use o uploader no sidebar.

## O que o app faz
- Concatena as 12 abas num único dataframe **tidy**
- Filtros por **site**, **parâmetro** e **intervalo de datas**
- KPIs rápidos (observações, sites, parâmetros, última data)
- **Gráfico de linha** por data (agregado por site/parâmetro)
- **Mapa** dos sites (lat/long)
- **Tabela** detalhada + **download CSV**
