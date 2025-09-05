import streamlit as st
import pandas as pd
import pydeck as pdk
from datetime import datetime
import os

# ----------------- Config / CSS -----------------
st.set_page_config(page_title="DAP Atlas – Methane POC", page_icon="🛰️", layout="wide")

def load_css():
    # tenta assets/styles.css; se não, tenta styles.css na raiz
    css_paths = ["assets/styles.css", "styles.css"]
    loaded = False
    for p in css_paths:
        if os.path.exists(p):
            with open(p, "r", encoding="utf-8") as f:
                st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)
            loaded = True
            break
    if not loaded:
        # CSS fallback (tema escuro básico) caso nenhum arquivo exista
        fallback = """
        .block-container { padding-top: 1.2rem; }
        body, .stMarkdown, .stText, .stApp { color:#E5E7EB!important; background:#0B1220!important; }
        section[data-testid="stSidebar"] { background:#121A2B!important; border-right:1px solid rgba(255,255,255,.06); }
        .topbar {display:flex;align-items:center;gap:12px;background:linear-gradient(90deg,rgba(14,165,164,.12),rgba(14,165,164,.04));
                 border:1px solid rgba(255,255,255,.06); padding:10px 14px; border-radius:14px; margin-bottom:14px;}
        .topbar h1{font-size:1.05rem;margin:0;color:#E5E7EB}
        .kpi-row{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px}
        .kpi{background:linear-gradient(180deg,rgba(255,255,255,.06),rgba(255,255,255,.03));
             border:1px solid rgba(255,255,255,.08);border-radius:16px;padding:14px 16px;box-shadow:0 6px 22px rgba(0,0,0,.2)}
        .kpi .label{font-size:.8rem;color:#A7B0BF;margin-bottom:6px}
        .kpi .value{font-size:1.4rem;font-weight:700;color:#F9FAFB}
        .kpi .sub{font-size:.78rem;color:#8FA3B8}
        .section-title{display:flex;align-items:center;gap:8px;margin:18px 0 8px;color:#E5E7EB;font-weight:600}
        .section-title .dot{width:8px;height:8px;border-radius:50%;background:#0EA5A4;display:inline-block}
        [data-testid="stDataFrame"]{border:1px solid rgba(255,255,255,.08);border-radius:12px;overflow:hidden}
        .footer{margin-top:12px;font-size:.78rem;color:#8FA3B8;border-top:1px dashed rgba(255,255,255,.12);padding-top:8px}
        """
        st.markdown(f"<style>{fallback}</style>", unsafe_allow_html=True)

load_css()

# ----------------- Data loading -----------------
@st.cache_data
def load_excel(path_or_buffer):
    xlsx = pd.ExcelFile(path_or_buffer)
    frames = []
    for sh in xlsx.sheet_names:
        df = pd.read_excel(xlsx, sheet_name=sh)
        frames.append((sh, df))
    return {sh: df for sh, df in frames}

def parse_sheet(df: pd.DataFrame, site: str) -> pd.DataFrame:
    cols = list(df.columns)
    start_idx = cols.index("Data")
    date_cols = cols[start_idx:]
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
            recs.append({
                "site": site, "lat": lat, "lon": lon,
                "parameter": param, "date": pd.to_datetime(d),
                "value": pd.to_numeric(v, errors="coerce"),
            })
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

# ----------------- Sidebar -----------------
st.sidebar.header("⚙️ Configurações")

default_path = "exemplo banco dados.xlsx"   # se você versionou um exemplo
uploaded = st.sidebar.file_uploader("Suba o Excel (12 abas, mesmo layout)", type=["xlsx"])
path = uploaded if uploaded is not None else default_path

try:
    sheets_dict = load_excel(path)
except Exception:
    st.error("Carregue um arquivo .xlsx no sidebar (mesmo layout do exemplo).")
    st.stop()

data = to_tidy(sheets_dict)

sites = sorted(data["site"].unique())
params = sorted(data["parameter"].unique())

sel_sites = st.sidebar.multiselect("🛠️ Sites", sites, default=sites)
sel_params = st.sidebar.multiselect("📊 Parâmetros", params, default=params)

min_d, max_d = data["date"].min(), data["date"].max()
start, end = st.sidebar.date_input(
    "📅 Intervalo de datas", value=(min_d, max_d), min_value=min_d, max_value=max_d
)

basemaps = {
    "Esri Streets": "World_Street_Map",
    "Esri Satellite": "World_Imagery",
    "Esri Topo": "World_Topo_Map",
}
bm = st.sidebar.selectbox("🗺️ Basemap", list(basemaps))
show_heat = st.sidebar.checkbox("Heatmap (Taxa Metano)", value=False)

# ----------------- Filtro -----------------
filt = (
    data["site"].isin(sel_sites)
    & data["parameter"].isin(sel_params)
    & data["date"].between(pd.to_datetime(start), pd.to_datetime(end))
)
data = data.loc[filt].copy()

# ----------------- Topbar + KPIs -----------------
st.markdown(
    '<div class="topbar"><h1>DAP Atlas – Methane & Metocean · 12 Sites</h1></div>',
    unsafe_allow_html=True,
)

def kpi_grid():
    obs = f"{len(data):,}".replace(",", ".")
    nsites = f"{data['site'].nunique():,}".replace(",", ".")
    nparams = f"{data['parameter'].nunique():,}".replace(",", ".")
    last_date = data["date"].max() if not data.empty else None
    last_txt = last_date.date().isoformat() if last_date is not None else "-"

    st.markdown('<div class="kpi-row">', unsafe_allow_html=True)
    for label, value, sub in [
        ("Observações", obs, "No período selecionado"),
        ("Sites ativos", nsites, "Com dados no filtro"),
        ("Parâmetros", nparams, "Métricas monitoradas"),
        ("Última data", last_txt, "Atualização do dataset"),
    ]:
        st.markdown(
            f'<div class="kpi"><div class="label">{label}</div>'
            f'<div class="value">{value}</div><div class="sub">{sub}</div></div>',
            unsafe_allow_html=True,
        )
    st.markdown("</div>", unsafe_allow_html=True)

kpi_grid()

# ----------------- Abas -----------------
tab1, tab2, tab3, tab4 = st.tabs(["📈 Tendência", "🏁 Ranking", "🗺️ Mapas", "🚨 Alertas"])

with tab1:
    st.markdown('<div class="section-title"><span class="dot"></span> Série temporal</div>', unsafe_allow_html=True)
    if data.empty:
        st.info("Seleção sem dados.")
    else:
        import altair as alt
        series = data.groupby(["date", "site", "parameter"], as_index=False)["value"].mean()
        use_ma = st.checkbox("Aplicar média móvel (7d)", value=False)
        if use_ma:
            series["value_ma7"] = series.groupby(["site","parameter"])["value"].transform(
                lambda s: s.rolling(7, min_periods=1).mean()
            )
            y_field = "value_ma7"
        else:
            y_field = "value"
        chart = (
            alt.Chart(series).mark_line()
            .encode(
                x="date:T",
                y=alt.Y(f"{y_field}:Q", title="Valor"),
                color="site:N",
                tooltip=["site","parameter","date:T","value:Q"],
            ).properties(height=340).interactive()
        )
        st.altair_chart(chart, use_container_width=True)

with tab2:
    st.markdown('<div class="section-title"><span class="dot"></span> Ranking por métrica</div>', unsafe_allow_html=True)
    if data.empty:
        st.info("Seleção sem dados.")
    else:
        metric = st.selectbox("Métrica", sorted(data["parameter"].unique()))
        rank = (
            data[data["parameter"] == metric]
            .groupby("site", as_index=False)["value"].mean()
            .sort_values("value", ascending=False)
        )
        st.dataframe(rank, use_container_width=True)
        import altair as alt
        bars = (
            alt.Chart(rank).mark_bar()
            .encode(
                x=alt.X("value:Q", title="Média no período"),
                y=alt.Y("site:N", sort="-x"),
                tooltip=["site","value"],
            ).properties(height=420)
        )
        st.altair_chart(bars, use_container_width=True)

with tab3:
    st.markdown('<div class="section-title"><span class="dot"></span> Mapa dos Sites</div>', unsafe_allow_html=True)
    if data.empty:
        st.info("Seleção sem dados.")
    else:
        sites_df = data.groupby(["site", "lat", "lon"], as_index=False).size()
        view_state = pdk.ViewState(
            latitude=sites_df["lat"].mean(),
            longitude=sites_df["lon"].mean(),
            zoom=4, pitch=0,
        )
        esri_layer = pdk.Layer(
            "TileLayer", data=None,
            get_tile_url=f"https://server.arcgisonline.com/ArcGIS/rest/services/{basemaps[bm]}/MapServer/tile/{{z}}/{{y}}/{{x}}"
        )
        points_layer = pdk.Layer(
            "ScatterplotLayer",
            data=sites_df.rename(columns={"lon":"longitude","lat":"latitude"}),
            get_position="[longitude, latitude]",
            get_radius=15000,
            get_fill_color=[255, 0, 0, 160],
            pickable=True,
        )
        deck_layers = [esri_layer, points_layer]

        if show_heat and "Taxa Metano" in data["parameter"].unique():
            heat = data[data["parameter"] == "Taxa Metano"].rename(columns={"lon":"longitude","lat":"latitude"})
            heat_layer = pdk.Layer(
                "HeatmapLayer",
                data=heat,
                get_position='[longitude, latitude]',
                get_weight="value",
                radiusPixels=40,
            )
            deck_layers = [esri_layer, heat_layer, points_layer]

        st.pydeck_chart(pdk.Deck(
            initial_view_state=view_state,
            layers=deck_layers,
            tooltip={"text": "{site}"}
        ))

with tab4:
    st.markdown('<div class="section-title"><span class="dot"></span> Regras de alerta</div>', unsafe_allow_html=True)
    if data.empty:
        st.info("Seleção sem dados.")
    else:
        limiar = st.number_input("Limiar de Taxa Metano", value=50.0, step=1.0)
        ult = (
            data[data["parameter"] == "Taxa Metano"]
            .sort_values("date")
            .groupby("site").tail(1)
        )
        alertas = ult[ult["value"] >= limiar][["site","value","date"]].sort_values("value", ascending=False)
        if alertas.empty:
            st.success("Nenhum alerta no momento ✅")
        else:
            st.error(f"{len(alertas)} site(s) acima do limiar")
            st.dataframe(alertas, use_container_width=True)

# ----------------- Export -----------------
st.download_button(
    "⬇️ Baixar CSV filtrado (seleção atual)",
    data.to_csv(index=False).encode("utf-8"),
    file_name="dashboard_selecao.csv",
    mime="text/csv",
)

st.markdown('<div class="footer">© DAP Sistemas Espaciais · Demo POC · deck.gl via PyDeck · tiles Esri.</div>', unsafe_allow_html=True)
