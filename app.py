import streamlit as st
import pandas as pd
import pydeck as pdk
import os, time

# ================== Config & CSS ==================
st.set_page_config(page_title="DAP Atlas – Methane POC", page_icon="🛰️", layout="wide")

def load_css():
    for p in ("assets/styles.css", "styles.css"):
        if os.path.exists(p):
            with open(p, "r", encoding="utf-8") as f:
                st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)
            return
    # Fallback (tema escuro básico)
    st.markdown("""
    <style>
    .block-container{padding-top:1.2rem}
    body,.stApp{color:#E5E7EB!important;background:#0B1220!important}
    section[data-testid="stSidebar"]{background:#121A2B!important;border-right:1px solid rgba(255,255,255,.06)}
    .topbar{display:flex;align-items:center;gap:12px;background:linear-gradient(90deg,rgba(14,165,164,.12),rgba(14,165,164,.04));
            border:1px solid rgba(255,255,255,.06);padding:10px 14px;border-radius:14px;margin-bottom:14px}
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
    </style>
    """, unsafe_allow_html=True)

load_css()

# ================== Utils (parser robusto) ==================
def _pick_col(df: pd.DataFrame, candidates):
    for c in candidates:
        if c in df.columns:
            return c
    norm = {str(c).strip().lower(): c for c in df.columns}
    for c in candidates:
        key = str(c).strip().lower()
        if key in norm:
            return norm[key]
    return None

def _to_float(cell):
    return float(str(cell).replace(",", ".").strip())

# ================== Load & Transform (com cache) ==================
@st.cache_data(ttl=900, max_entries=4)
def load_excel(path_or_buffer):
    xlsx = pd.ExcelFile(path_or_buffer)
    frames = []
    for sh in xlsx.sheet_names:
        df = pd.read_excel(xlsx, sheet_name=sh)
        frames.append((sh, df))
    return {sh: df for sh, df in frames}

def parse_sheet(df: pd.DataFrame, site: str) -> pd.DataFrame:
    lat_col = _pick_col(df, ["Lat", "Latitude", "LAT"])
    lon_col = _pick_col(df, ["Long", "Lon", "Longitude", "LONG"])
    if lat_col is None or lon_col is None:
        raise ValueError(f"Aba '{site}': faltam colunas Lat/Long.")

    cols = list(df.columns)
    start_idx = cols.index("Data") if "Data" in cols else None
    if start_idx is None:
        for i, c in enumerate(cols):
            cell = df.iloc[0, i] if 0 in df.index else None
            if pd.to_datetime(cell, errors="coerce") is not pd.NaT:
                start_idx = i
                break
    if start_idx is None:
        raise ValueError(f"Aba '{site}': não identifiquei as colunas de data.")

    date_cols = cols[start_idx:]
    dates = pd.to_datetime(df.loc[df.index[0], date_cols], errors="coerce")
    if dates.isna().all():
        raise ValueError(f"Aba '{site}': cabeçalho de datas inválido.")

    par_col = _pick_col(df, ["Parametro", "Parâmetro", "parametro", "parameter"])
    if par_col is None:
        raise ValueError(f"Aba '{site}': não encontrei a coluna de parâmetro.")

    try:
        lat = _to_float(df.loc[df.index[0], lat_col])
        lon = _to_float(df.loc[df.index[0], lon_col])
    except Exception:
        raise ValueError(f"Aba '{site}': Lat/Long da linha 0 não numéricos.")

    value_rows = df.iloc[1:].copy().reset_index(drop=True)
    recs = []
    for _, row in value_rows.iterrows():
        param = str(row[par_col]).strip()
        if not param or param.lower() in ("nan", "none"):
            continue
        for i, c in enumerate(date_cols):
            d = dates.iloc[i]
            v = row.get(c, None)
            if pd.isna(d) or pd.isna(v):
                continue
            recs.append({
                "site": site, "lat": lat, "lon": lon,
                "parameter": param, "date": pd.to_datetime(d),
                "value": pd.to_numeric(str(v).replace(",", "."), errors="coerce"),
            })
    out = pd.DataFrame(recs)
    if out.empty:
        raise ValueError(f"Aba '{site}': nenhum valor válido após parse.")
    return out

@st.cache_data(ttl=900, max_entries=4)
def to_tidy_cached(sheets_dict):
    parts = []
    for sh, df in sheets_dict.items():
        try:
            parts.append(parse_sheet(df, sh))
        except Exception as e:
            st.warning(f"⚠️ {e}")
    if not parts:
        raise RuntimeError("Nenhuma aba válida após o parse.")
    tidy = pd.concat(parts, ignore_index=True)
    tidy.sort_values(["site", "parameter", "date"], inplace=True)
    return tidy

# ================== Sidebar & Data ==================
st.sidebar.header("⚙️ Configurações")

uploaded = st.sidebar.file_uploader("Suba o Excel (12 abas, mesmo layout)", type=["xlsx"])
default_example = "exemplo banco dados.xlsx"
if uploaded is None and not os.path.exists(default_example):
    st.info("⬅️ Envie o arquivo .xlsx no sidebar (ou inclua 'exemplo banco dados.xlsx' no repositório).")
    st.stop()
path = uploaded if uploaded is not None else default_example

t0 = time.perf_counter()
with st.spinner("Carregando planilha..."):
    sheets_dict = load_excel(path)
t1 = time.perf_counter()
with st.spinner("Transformando dados..."):
    data = to_tidy_cached(sheets_dict)
t2 = time.perf_counter()
st.caption(f"⏱️ Tempo: load {t1-t0:.2f}s · transform {t2-t1:.2f}s")

with st.expander("🧪 Debug – estrutura da planilha"):
    st.write("Abas:", list(sheets_dict.keys()))
    for sh, df in list(sheets_dict.items())[:3]:
        st.write(f"**Aba:** {sh}")
        st.write("Colunas:", list(df.columns))
        st.dataframe(df.head(5), use_container_width=True)

# ================== Filtros ==================
sites = sorted(data["site"].unique())
params = sorted(data["parameter"].unique())

sel_sites = st.sidebar.multiselect("🛠️ Sites", sites, default=sites)
sel_params = st.sidebar.multiselect("📊 Parâmetros", params, default=params)

min_d, max_d = data["date"].min(), data["date"].max()
start, end = st.sidebar.date_input(
    "📅 Intervalo de datas", value=(min_d, max_d), min_value=min_d, max_value=max_d
)

BASEMAPS = {
    "Esri Streets": "World_Street_Map",
    "Esri Satellite": "World_Imagery",
    "Esri Topo": "World_Topo_Map",
}
bm_name = st.sidebar.selectbox("🗺️ Basemap", list(BASEMAPS))
bm_id = BASEMAPS[bm_name]  # sempre string
show_heat = st.sidebar.checkbox("Heatmap (Taxa Metano)", value=False)

filt = (
    data["site"].isin(sel_sites)
    & data["parameter"].isin(sel_params)
    & data["date"].between(pd.to_datetime(start), pd.to_datetime(end))
)
data = data.loc[filt].copy()

# ================== Header & KPIs ==================
st.markdown('<div class="topbar"><h1>DAP Atlas – Methane & Metocean · 12 Sites</h1></div>', unsafe_allow_html=True)

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

# ================== Abas ==================
tab1, tab2, tab3, tab4 = st.tabs(["📈 Tendência", "🏁 Ranking", "🗺️ Mapas", "🚨 Alertas"])

# --- Tendência temporal
with tab1:
    st.markdown('<div class="section-title"><span class="dot"></span> Série temporal</div>', unsafe_allow_html=True)
    if data.empty:
        st.info("Seleção sem dados.")
    else:
        import altair as alt
        series = data.groupby(["date", "site", "parameter"], as_index=False)["value"].mean()
        use_ma = st.checkbox("Aplicar média móvel (7d)", value=False)
        y_field = "value"
        if use_ma:
            series["value_ma7"] = series.groupby(["site","parameter"])["value"].transform(
                lambda s: s.rolling(7, min_periods=1).mean()
            )
            y_field = "value_ma7"
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

# --- Ranking
with tab2:
    st.markdown('<div class="section-title"><span class="dot"></span> Ranking por métrica</div>', unsafe_allow_html=True)
    if data.empty:
        st.info("Seleção sem dados.")
    else:
        import altair as alt
        metric = st.selectbox("Métrica", sorted(data["parameter"].unique()))
        rank = (
            data[data["parameter"] == metric]
            .groupby("site", as_index=False)["value"].mean()
            .sort_values("value", ascending=False)
        )
        st.dataframe(rank, use_container_width=True)
        bars = (
            alt.Chart(rank).mark_bar()
            .encode(
                x=alt.X("value:Q", title="Média no período"),
                y=alt.Y("site:N", sort="-x"),
                tooltip=["site","value"],
            ).properties(height=420)
        )
        st.altair_chart(bars, use_container_width=True)

# --- Mapas (refresh garantido + key seguro)
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

        esri_url = (
            f"https://server.arcgisonline.com/ArcGIS/rest/services/"
            f"{bm_id}/MapServer/tile/{{z}}/{{y}}/{{x}}?fresh={bm_id}"
        )

        esri_layer = pdk.Layer(
            "TileLayer",
            id=f"esri-{bm_id}",          # muda com o basemap -> rebuild
            data=[{"bm": bm_id}],        # payload muda -> deck.gl refaz a layer
            get_tile_url=esri_url,
        )

        points_layer = pdk.Layer(
            "ScatterplotLayer",
            id="sites-points",
            data=sites_df.rename(columns={"lon":"longitude","lat":"latitude"}),
            get_position="[longitude, latitude]",
            get_radius=15000,
            get_fill_color=[255, 0, 0, 160],
            pickable=True,
        )

        layers = [esri_layer, points_layer]

        if show_heat and "Taxa Metano" in data["parameter"].unique():
            heat = data[data["parameter"] == "Taxa Metano"].rename(columns={"lon":"longitude","lat":"latitude"})
            heat_layer = pdk.Layer(
                "HeatmapLayer",
                id=f"heat-{bm_id}",
                data=heat,
                get_position='[longitude, latitude]',
                get_weight="value",
                radiusPixels=40,
            )
            layers = [esri_layer, heat_layer, points_layer]

        deck = pdk.Deck(
            initial_view_state=view_state,
            layers=layers,
            tooltip={"text": "{site}"},
            map_style=None,
        )

        # 🔧 key sempre como string (evita TypeError)
        st.pydeck_chart(deck)

# --- Alertas
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

# --- Export
st.download_button(
    "⬇️ Baixar CSV filtrado (seleção atual)",
    data.to_csv(index=False).encode("utf-8"),
    file_name="dashboard_selecao.csv",
    mime="text/csv",
)

st.markdown('<div class="footer">© DAP Sistemas Espaciais · Demo POC · deck.gl via PyDeck · tiles Esri.</div>', unsafe_allow_html=True)
