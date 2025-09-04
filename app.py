import streamlit as st
import pandas as pd
import pydeck as pdk
from datetime import datetime

st.set_page_config(page_title="Painel OGMP L5 – 12 Sites", layout="wide")

@st.cache_data
def load_excel(path_or_buffer):
    xlsx = pd.ExcelFile(path_or_buffer)
    sheets = xlsx.sheet_names
    frames = []
    for sh in sheets:
        df = pd.read_excel(xlsx, sheet_name=sh)
        frames.append((sh, df))
    return sheets, {sh: df for sh, df in frames}

def parse_sheet(df: pd.DataFrame, site: str) -> pd.DataFrame:
    cols = list(df.columns)
    start_idx = cols.index("Data")
    date_cols = cols[start_idx:]
    # datas na linha 0
    dates = pd.to_datetime(df.loc[0, date_cols], errors="coerce")
    lat = float(df.loc[0, "Lat"])
    lon = float(df.loc[0, "Long"])
    value_rows = df.iloc[1:].copy().reset_index(drop=True)
    records = []
    for _, row in value_rows.iterrows():
        param = str(row["Parametro"]).strip()
        for i, c in enumerate(date_cols):
            d = dates.iloc[i]
            v = row[c]
            if pd.isna(d) or pd.isna(v):
                continue
            records.append(
                {"site": site, "lat": lat, "lon": lon,
                 "parameter": param, "date": pd.to_datetime(d),
                 "value": pd.to_numeric(v, errors="coerce")}
            )
    return pd.DataFrame(records)

def to_tidy(sheets_dict):
    parts = []
    for sh, df in sheets_dict.items():
        try:
            parts.append(parse_sheet(df, sh))
        except Exception as e:
            st.warning(f"Falha ao processar a aba '{sh}': {e}")
    tidy = pd.concat(parts, ignore_index=True)
    tidy.sort_values(["site", "parameter", "date"], inplace=True)
    return tidy

# Sidebar
st.sidebar.header("⚙️ Configurações")
default_path = "exemplo banco dados.xlsx"
uploaded = st.sidebar.file_uploader(
    "Suba o Excel com as 12 abas (mesmo layout)", type=["xlsx"]
)
path = uploaded if uploaded is not None else default_path

sheets, sheets_dict = load_excel(path)
tidy = to_tidy(sheets_dict)

sites = sorted(tidy["site"].unique())
params = sorted(tidy["parameter"].unique())

sel_sites = st.sidebar.multiselect("🛠️ Sites", sites, default=sites)
sel_params = st.sidebar.multiselect("📊 Parâmetros", params, default=params)

# Date filter
min_d, max_d = tidy["date"].min(), tidy["date"].max()
start, end = st.sidebar.date_input(
    "📅 Intervalo de datas",
    value=(min_d, max_d),
    min_value=min_d,
    max_value=max_d,
)

filt = (
    tidy["site"].isin(sel_sites)
    & tidy["parameter"].isin(sel_params)
    & tidy["date"].between(pd.to_datetime(start), pd.to_datetime(end))
)
data = tidy.loc[filt].copy()

# Header
st.title("📈 Painel Methane & Metocean – 12 Sites")
st.caption("Fonte: planilha consolidada em múltiplas abas.")

# KPIs
col1, col2, col3, col4 = st.columns(4)
with col1:
    st.metric("Observações", f"{len(data):,}".replace(",", "."))
with col2:
    st.metric("Sites ativos", f"{data['site'].nunique():,}".replace(",", "."))
with col3:
    st.metric("Parâmetros", f"{data['parameter'].nunique():,}".replace(",", "."))
with col4:
    last_date = data["date"].max()
    st.metric(
        "Última data",
        last_date.date().isoformat() if pd.notna(last_date) else "-",
    )

# Charts
st.subheader("Tendência temporal")
if data.empty:
    st.info("Seleção sem dados.")
else:
    # Linha temporal agregada por site & parâmetro
    line_data = data.groupby(
        ["date", "site", "parameter"], as_index=False
    )["value"].mean()
    import altair as alt

    line_chart = (
        alt.Chart(line_data)
        .mark_line()
        .encode(
            x="date:T",
            y="value:Q",
            color=alt.Color("site:N"),
            tooltip=["site", "parameter", "date:T", "value:Q"],
        )
        .properties(height=300)
        .interactive()
    )
    st.altair_chart(line_chart, use_container_width=True)

# Map (Esri World Street Map como fundo)
st.subheader("Mapa dos sites")
sites_df = data.groupby(["site", "lat", "lon"], as_index=False).size()
if sites_df.empty:
    st.info("Sem coordenadas para exibir.")
else:
    view_state = pdk.ViewState(
        latitude=sites_df["lat"].mean(),
        longitude=sites_df["lon"].mean(),
        zoom=4,
        pitch=0,
    )

    # Basemap Esri
    esri_layer = pdk.Layer(
        "TileLayer",
        data=None,
        get_tile_url="https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}",
    )

    # Pontos dos sites
    layer_sites = pdk.Layer(
        "ScatterplotLayer",
        data=sites_df.rename(columns={"lon": "longitude", "lat": "latitude"}),
        get_position='[longitude, latitude]',
        get_radius=15000,
        get_fill_color=[255, 0, 0, 160],
        pickable=True,
    )

    deck = pdk.Deck(
        initial_view_state=view_state,
        layers=[esri_layer, layer_sites],
        tooltip={"text": "{site}"},
    )
    st.pydeck_chart(deck)

# Detail
st.subheader("Tabela detalhada")
st.dataframe(
    data.sort_values(["site", "parameter", "date"]), use_container_width=True
)

# Download
st.download_button(
    "⬇️ Baixar CSV filtrado",
    data.to_csv(index=False).encode("utf-8"),
    file_name="dados_filtrados.csv",
    mime="text/csv",
)

st.markdown("---")
st.caption(
    "💡 O app entende o layout desta planilha: primeira linha com datas por coluna e linhas seguintes com valores por parâmetro. Lat/Long na primeira linha."
)
