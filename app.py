import streamlit as st
import pandas as pd
import pydeck as pdk
from datetime import datetime

st.set_page_config(page_title="Painel OGMP L5 – 12 Sites", layout="wide")

# -----------------------------
# Carga e transformação de dados
# -----------------------------
@st.cache_data
def load_excel(path_or_buffer):
    xlsx = pd.ExcelFile(path_or_buffer)
    sheets = xlsx.sheet_names
    frames = []
    for sh in sheets:
        df = pd.read_excel(xlsx, sheet_name=sh)
        frames.append((sh, df))
    return {sh: df for sh, df in frames}

def parse_sheet(df: pd.DataFrame, site: str) -> pd.DataFrame:
    cols = list(df.columns)
    start_idx = cols.index("Data")
    date_cols = cols[start_idx:]
    # datas na linha 0; lat/long na linha 0
    dates = pd.to_datetime(df.loc[0, date_cols], errors="coerce")
    lat = float(df.loc[0, "Lat"])
    lon = float(df.loc[0, "Long"])
    value_rows = df.iloc[1:].copy().reset_index(drop=True)
    recs = []
    for _, row in value_rows.iterrows():
        param = str(row["Parametro"]).strip()
        for i, c in enumerate(date_cols):
            d = dates.iloc[i]
            v = row[c]
            if pd.isna(d) or pd.isna(v):
                continue
            recs.append(
                {
                    "site": site,
                    "lat": lat,
                    "lon": lon,
                    "parameter": param,
                    "date": pd.to_datetime(d),
                    "value": pd.to_numeric(v, errors="coerce"),
                }
            )
    return pd.DataFrame(recs)

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

# -----------------------------
# Entrada de dados
# -----------------------------
st.sidebar.header("⚙️ Configurações")
default_path = "exemplo banco dados.xlsx"  # opcional, se você versionou o exemplo
uploaded = st.sidebar.file_uploader("Suba o Excel (12 abas, mesmo layout)", type=["xlsx"])
path = uploaded if uploaded is not None else default_path

try:
    sheets_dict = load_excel(path)
except Exception:
    st.error("Carregue um arquivo .xlsx no sidebar (mesmo layout do exemplo).")
    st.stop()

data = to_tidy(sheets_dict)

# -----------------------------
# Filtros
# -----------------------------
sites = sorted(data["site"].unique())
params = sorted(data["parameter"].unique())

sel_sites = st.sidebar.multiselect("🛠️ Sites", sites, default=sites)
sel_params = st.sidebar.multiselect("📊 Parâmetros", params, default=params)

min_d, max_d = data["date"].min(), data["date"].max()
start, end = st.sidebar.date_input(
    "📅 Intervalo de datas",
    value=(min_d, max_d),
    min_value=min_d,
    max_value=max_d,
)

filt = (
    data["site"].isin(sel_sites)
    & data["parameter"].isin(sel_params)
    & data["date"].between(pd.to_datetime(start), pd.to_datetime(end))
)
data = data.loc[filt].copy()

# -----------------------------
# Cabeçalho e KPIs
# -----------------------------
st.title("📈 Painel Methane & Metocean – 12 Sites")
st.caption("Fonte: planilha consolidada em múltiplas abas (datas na linha 0; lat/long na primeira linha).")

col1, col2, col3, col4 = st.columns(4)
with col1:
    st.metric("Observações", f"{len(data):,}".replace(",", "."))
with col2:
    st.metric("Sites ativos", f"{data['site'].nunique():,}".replace(",", "."))
with col3:
    st.metric("Parâmetros", f"{data['parameter'].nunique():,}".replace(",", "."))
with col4:
    last_date = data["date"].max() if not data.empty else None
    st.metric("Última data", last_date.date().isoformat() if last_date is not None else "-")

# -----------------------------
# Abas do dashboard
# -----------------------------
tab1, tab2, tab3, tab4 = st.tabs(["📈 Tendência", "🏁 Ranking", "🗺️ Mapas", "🚨 Alertas"])

# Tendência temporal
with tab1:
    if data.empty:
        st.info("Seleção sem dados.")
    else:
        import altair as alt
        series = data.groupby(["date", "site", "parameter"], as_index=False)["value"].mean()
        st.altair_chart(
            alt.Chart(series)
            .mark_line()
            .encode(
                x="date:T",
                y="value:Q",
                color="site:N",
                tooltip=["site", "parameter", "date:T", "value:Q"],
            )
            .properties(height=320),
            use_container_width=True,
        )

# Ranking por métrica
with tab2:
    if data.empty:
        st.info("Seleção sem dados.")
    else:
        metric = st.selectbox("Métrica", sorted(data["parameter"].unique()))
        rank = (
            data[data["parameter"] == metric]
            .groupby("site", as_index=False)["value"]
            .mean()
            .sort_values("value", ascending=False)
        )
        st.dataframe(rank, use_container_width=True)
        import altair as alt
        st.altair_chart(
            alt.Chart(rank)
            .mark_bar()
            .encode(
                x="value:Q",
                y=alt.Y("site:N", sort="-x"),
                tooltip=["site", "value"],
            )
            .properties(height=420),
            use_container_width=True,
        )

# Mapas (Esri + pontos + heatmap opcional)
with tab3:
    if data.empty:
        st.info("Seleção sem dados.")
    else:
        sites_df = data.groupby(["site", "lat", "lon"], as_index=False).size()
        view_state = pdk.ViewState(
            latitude=sites_df["lat"].mean(),
            longitude=sites_df["lon"].mean(),
            zoom=4,
            pitch=0,
        )

        # Basemap Esri Streets (sem token)
        esri_layer = pdk.Layer(
            "TileLayer",
            data=None,
            get_tile_url=(
                "https://server.arcgisonline.com/ArcGIS/rest/services/"
                "World_Street_Map/MapServer/tile/{z}/{y}/{x}"
            ),
        )

        points_layer = pdk.Layer(
            "ScatterplotLayer",
            data=sites_df.rename(columns={"lon": "longitude", "lat": "latitude"}),
            get_position="[longitude, latitude]",
            get_radius=15000,
            get_fill_color=[255, 0, 0, 160],
            pickable=True,
        )

        deck_layers = [esri_layer, points_layer]

        show_heat = st.checkbox("Mostrar Heatmap (por Taxa Metano)", value=False)
        if show_heat and "Taxa Metano" in data["parameter"].unique():
            heat = data[data["parameter"] == "Taxa Metano"].rename(
                columns={"lon": "longitude", "lat": "latitude"}
            )
            heat_layer = pdk.Layer(
                "HeatmapLayer",
                data=heat,
                get_position="[longitude, latitude]",
                get_weight="value",
                radiusPixels=40,
            )
            deck_layers = [esri_layer, heat_layer, points_layer]

        st.pydeck_chart(
            pdk.Deck(
                initial_view_state=view_state,
                layers=deck_layers,
                tooltip={"text": "{site}"},
            )
        )

# Alertas por limiar (exemplo com Taxa Metano)
with tab4:
    if data.empty:
        st.info("Seleção sem dados.")
    else:
        st.write("Defina limites para disparar alertas (ex.: Taxa Metano).")
        limiar = st.number_input("Limiar de Taxa Metano", value=50.0, step=1.0)
        ult = (
            data[data["parameter"] == "Taxa Metano"]
            .sort_values("date")
            .groupby("site")
            .tail(1)
        )
        alertas = (
            ult[ult["value"] >= limiar][["site", "value", "date"]]
            .sort_values("value", ascending=False)
        )

        if alertas.empty:
            st.success("Nenhum alerta no momento ✅")
        else:
            st.error(f"{len(alertas)} site(s) acima do limiar")
            st.dataframe(alertas, use_container_width=True)

# -----------------------------
# Exportação
# -----------------------------
st.download_button(
    "⬇️ Baixar CSV filtrado (seleção atual)",
    data.to_csv(index=False).encode("utf-8"),
    file_name="dashboard_selecao.csv",
    mime="text/csv",
)

st.markdown("---")
st.caption("💡 Dica: ajuste sites, parâmetros e período no sidebar. O heatmap usa 'Taxa Metano'.")
