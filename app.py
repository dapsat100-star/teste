import streamlit as st
import pandas as pd
import numpy as np
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
        for i, _ in enumerate(cols):
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

min_d, max_d = pd.to_datetime(data["date"].min()).date(), pd.to_datetime(data["date"].max()).date()
start, end = st.sidebar.date_input(
    "📅 Intervalo de datas", value=(min_d, max_d), min_value=min_d, max_value=max_d
)

BASEMAPS = {
    "Esri Streets": "World_Street_Map",
    "Esri Satellite": "World_Imagery",
    "Esri Topo": "World_Topo_Map",
}
bm_name = st.sidebar.selectbox("🗺️ Basemap", list(BASEMAPS))
bm_id = BASEMAPS[bm_name]  # string
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
    last_txt = pd.to_datetime(last_date).date().isoformat() if last_date is not None else "-"

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
tab1, tab2, tab3, tab4, tab5 = st.tabs(["📈 Tendência", "🏁 Ranking", "🗺️ Mapas", "🚨 Alertas", "🔗 Correlação"])

# --- 📈 Tendência temporal (com ferramentas estatísticas)
with tab1:
    st.markdown('<div class="section-title"><span class="dot"></span> Série temporal (ferramentas estatísticas)</div>', unsafe_allow_html=True)
    if data.empty:
        st.info("Seleção sem dados.")
    else:
        import altair as alt

        # ---------------- UI (controles) ----------------
        c1, c2, c3 = st.columns(3)
        with c1:
            freq = st.selectbox("Frequência", ["Diário", "Semanal", "Mensal"], index=0)
            agg_fun = st.selectbox("Agregação", ["média", "mediana", "máximo", "mínimo"], index=0)
        with c2:
            smooth_type = st.selectbox("Suavização", ["Nenhuma", "SMA (média móvel)", "EWMA (exponencial)"], index=0)
            win = st.slider("Janela/Span", min_value=3, max_value=60, value=7, step=1)
        with c3:
            outlier_filter = st.selectbox("Filtro de outliers", ["Nenhum", "Z-score", "IQR"], index=0)
            band_type = st.selectbox("Bandas", ["Nenhuma", "Confiança (±k·σ)", "Quantis (p10–p90)"], index=0)

        k_sigma = st.slider("k (para banda de confiança)", 1.0, 4.0, 2.0, 0.5)
        show_trend = st.checkbox("Mostrar tendência linear", value=False)
        normalize = st.checkbox("Normalizar pela linha base (primeira janela)", value=False)
        mark_anoms = st.checkbox("Marcar anomalias (acima de banda)", value=False)

        # ---------------- Prep (agrupamento) ----------------
        freq_code = {"Diário": "D", "Semanal": "W", "Mensal": "M"}[freq]
        agg_map = {"média": "mean", "mediana": "median", "máximo": "max", "mínimo": "min"}
        f_agg = agg_map[agg_fun]

        base = data[["date", "site", "parameter", "value"]].copy()
        base["date"] = pd.to_datetime(base["date"])

        series = (
            base.set_index("date")
            .groupby(["site", "parameter"])
            .resample(freq_code)["value"]
            .agg(f_agg)
            .reset_index()
            .dropna(subset=["value"])
        )

        # ---------------- Filtro de outliers ----------------
        if outlier_filter != "Nenhum":
            def _filter_group(g):
                x = g["value"].astype(float)
                if outlier_filter == "Z-score":
                    mu, sigma = x.mean(), x.std(ddof=0)
                    if sigma == 0 or np.isnan(sigma):
                        return g
                    z = (x - mu) / sigma
                    return g.loc[z.abs() <= 3]
                else:  # IQR
                    q1, q3 = x.quantile(0.25), x.quantile(0.75)
                    iqr = q3 - q1
                    lo, hi = q1 - 1.5 * iqr, q3 + 1.5 * iqr
                    return g.loc[(x >= lo) & (x <= hi)]
            series = series.groupby(["site", "parameter"], group_keys=False).apply(_filter_group)

        # ---------------- Suavização ----------------
        y_col = "value"
        if smooth_type == "SMA (média móvel)":
            series["value_sma"] = (
                series.groupby(["site", "parameter"])["value"]
                .transform(lambda s: s.rolling(win, min_periods=1).mean())
            )
            y_col = "value_sma"
        elif smooth_type == "EWMA (exponencial)":
            series["value_ewm"] = (
                series.groupby(["site", "parameter"])["value"]
                .transform(lambda s: s.ewm(span=win, adjust=False).mean())
            )
            y_col = "value_ewm"

        # ---------------- Bandas ----------------
        band_lo, band_hi = None, None
        if band_type == "Confiança (±k·σ)":
            roll_mean = series.groupby(["site","parameter"])["value"].transform(
                lambda s: s.rolling(win, min_periods=2).mean()
            )
            roll_std = series.groupby(["site","parameter"])["value"].transform(
                lambda s: s.rolling(win, min_periods=2).std(ddof=0)
            )
            series["band_lo"] = roll_mean - k_sigma * roll_std
            series["band_hi"] = roll_mean + k_sigma * roll_std
            band_lo, band_hi = "band_lo", "band_hi"

        elif band_type == "Quantis (p10–p90)":
            def _quant_bands(g):
                s = g["value"]
                q10 = s.rolling(win, min_periods=2).quantile(0.10)
                q90 = s.rolling(win, min_periods=2).quantile(0.90)
                g["band_lo"] = q10
                g["band_hi"] = q90
                return g
            series = series.groupby(["site","parameter"], group_keys=False).apply(_quant_bands)
            band_lo, band_hi = "band_lo", "band_hi"

        # ---------------- Normalização (linha base) ----------------
        if normalize:
            def _norm(g):
                base_val = g[y_col].iloc[:max(1, min(len(g), win))].mean()
                g[y_col] = g[y_col] - base_val
                if band_lo and band_hi:
                    g[band_lo] = g[band_lo] - base_val
                    g[band_hi] = g[band_hi] - base_val
                return g
            series = series.groupby(["site","parameter"], group_keys=False).apply(_norm)

        # ---------------- Tendência linear ----------------
        trend_df = None
        if show_trend:
            rows = []
            for (sname, par), g in series.groupby(["site","parameter"]):
                g2 = g.dropna(subset=[y_col]).copy()
                if g2.empty:
                    continue
                x = (g2["date"] - g2["date"].min()).dt.total_seconds() / 86400.0
                y = g2[y_col].values.astype(float)
                if len(g2) >= 2:
                    a, b = np.polyfit(x, y, 1)  # y = a*x + b
                    y_fit = a * x + b
                    g2["trend"] = y_fit
                    rows.append(g2[["date","trend"]].assign(site=sname, parameter=par))
            if rows:
                trend_df = pd.concat(rows, ignore_index=True)

        # ---------------- Anomalias (fora da banda) ----------------
        anoms = None
        if (mark_anoms and band_lo and band_hi):
            anoms = series[(series[y_col] > series[band_hi]) | (series[y_col] < series[band_lo])]

        # ---------------- Gráfico Altair ----------------
        base_chart = alt.Chart(series).mark_line().encode(
            x="date:T",
            y=alt.Y(f"{y_col}:Q", title="Valor"),
            color="site:N",
            tooltip=["site","parameter","date:T", alt.Tooltip(y_col, type="quantitative", title="valor")]
        ).properties(height=360)

        if band_lo and band_hi:
            band_area = alt.Chart(series).mark_area(opacity=0.18).encode(
                x="date:T",
                y=f"{band_lo}:Q",
                y2=f"{band_hi}:Q",
                color="site:N"
            )
            chart = (band_area + base_chart).interactive()
        else:
            chart = base_chart.interactive()

        if trend_df is not None and not trend_df.empty:
            trend_chart = alt.Chart(trend_df).mark_line(strokeDash=[6,3]).encode(
                x="date:T", y="trend:Q", color="site:N"
            )
            chart = (chart + trend_chart)

        if anoms is not None and not anoms.empty:
            points = alt.Chart(anoms).mark_point(size=60).encode(
                x="date:T", y=f"{y_col}:Q", color="site:N",
                tooltip=["site","parameter","date:T", y_col]
            )
            chart = (chart + points)

        st.altair_chart(chart, use_container_width=True)

        st.markdown("**Resumo estatístico por (site, parâmetro)**")
        summary = (
            series.groupby(["site","parameter"])[y_col]
            .agg(n="count", mean="mean", median="median", std="std")
            .reset_index()
        )
        summary["cv_%"] = (summary["std"] / summary["mean"]).replace([np.inf, -np.inf], np.nan) * 100
        st.dataframe(summary, use_container_width=True)

# --- 🏁 Ranking
with tab2:
    st.markdown('<div class="section-title"><span class="dot"></span> Ranking por métrica</div>', unsafe_allow_html=True)
    if data.empty:
        st.info("Seleção sem dados.")
    else:
        import altair as alt
        metric = st.selectbox("Métrica", sorted(data["parameter"].unique()))
        rank = (
            data[data["parameter"] == metric]
            .groupby("site", as_index=False)["value"]
            .agg(media="mean", mediana="median", desvio="std", n="count")
            .sort_values("media", ascending=False)
        )
        rank["cv_%"] = (rank["desvio"] / rank["media"]).replace([np.inf, -np.inf], np.nan) * 100
        st.dataframe(rank, use_container_width=True)
        bars = (
            alt.Chart(rank).mark_bar()
            .encode(
                x=alt.X("media:Q", title="Média no período"),
                y=alt.Y("site:N", sort="-x"),
                tooltip=["site","media","mediana","desvio","cv_%","n"],
            ).properties(height=420)
        )
        st.altair_chart(bars, use_container_width=True)

# --- 🗺️ Mapas (Folium + Esri, sem Mapbox)
with tab3:
    st.markdown('<div class="section-title"><span class="dot"></span> Mapa dos Sites</div>', unsafe_allow_html=True)
    if data.empty:
        st.info("Seleção sem dados.")
    else:
        import folium
        from folium.plugins import HeatMap
        from streamlit_folium import st_folium

        sites_df = data.groupby(["site", "lat", "lon"], as_index=False).size()
        center_lat = float(sites_df["lat"].mean())
        center_lon = float(sites_df["lon"].mean())

        esri_url = (
            f"https://server.arcgisonline.com/ArcGIS/rest/services/"
            f"{bm_id}/MapServer/tile/{{z}}/{{y}}/{{x}}"
        )

        m = folium.Map(location=[center_lat, center_lon], zoom_start=4, tiles=None, control_scale=True)
        folium.TileLayer(
            tiles=esri_url,
            name=bm_name,
            attr="Esri",
            overlay=False,
            control=True,
        ).add_to(m)

        for _, r in sites_df.iterrows():
            folium.CircleMarker(
                location=[float(r["lat"]), float(r["lon"])],
                radius=7,
                color="#ff4444",
                fill=True,
                fill_opacity=0.7,
                tooltip=str(r["site"]),
            ).add_to(m)

        if show_heat and "Taxa Metano" in data["parameter"].unique():
            heat_df = data[data["parameter"] == "Taxa Metano"][["lat", "lon", "value"]].dropna()
            if not heat_df.empty:
                HeatMap(
                    data=heat_df[["lat", "lon", "value"]].values.tolist(),
                    radius=25,
                    blur=18,
                    max_zoom=6,
                ).add_to(m)

        folium.LayerControl(collapsed=False).add_to(m)
        st_folium(m, height=560, use_container_width=True)

# --- 🚨 Alertas
with tab4:
    st.markdown('<div class="section-title"><span class="dot"></span> Regras de alerta</div>', unsafe_allow_html=True)
    if data.empty:
        st.info("Seleção sem dados.")
    else:
        limiar = st.number_input("Limiar de Taxa Metano", value=50.0, step=1.0)
        consecutivos = st.slider("Pontos consecutivos acima do limiar (histerese)", 1, 5, 1, 1)

        ult = (
            data[data["parameter"] == "Taxa Metano"]
            .sort_values(["site","date"])
            .copy()
        )

        # Sinaliza consecutivos por site
        def _consec(g):
            g["acima"] = (g["value"] >= limiar).astype(int)
            # contador de streaks
            streak = []
            c = 0
            for v in g["acima"]:
                c = c + 1 if v == 1 else 0
                streak.append(c)
            g["streak"] = streak
            return g

        ult = ult.groupby("site", group_keys=False).apply(_consec)
        alertas = ult[ult["streak"] >= consecutivos].groupby("site").tail(1)[["site","value","date"]].sort_values("value", ascending=False)

        if alertas.empty:
            st.success("Nenhum alerta no momento ✅")
        else:
            st.error(f"{len(alertas)} site(s) acima do limiar")
            st.dataframe(alertas, use_container_width=True)

# --- 🔗 Correlação
with tab5:
    st.markdown('<div class="section-title"><span class="dot"></span> Correlação entre métricas</div>', unsafe_allow_html=True)
    if data.empty:
        st.info("Seleção sem dados.")
    else:
        import altair as alt

        mode = st.radio("Escopo", ["Global (todos os sites)", "Por site"], horizontal=True)
        if mode == "Global (todos os sites)":
            dfp = (data.groupby(["date","parameter"])["value"].mean().reset_index()
                      .pivot(index="date", columns="parameter", values="value"))
        else:
            site_sel = st.selectbox("Site", sorted(data["site"].unique()))
            dfp = (data[data["site"] == site_sel]
                   .pivot_table(index="date", columns="parameter", values="value", aggfunc="mean"))
        dfp = dfp.dropna(how="any")

        if dfp.shape[1] < 2 or dfp.empty:
            st.info("Dados insuficientes para correlação.")
        else:
            corr = dfp.corr(method="pearson")
            corr_reset = corr.reset_index().melt(id_vars=corr.index.name, var_name="param2", value_name="corr")
            corr_reset.rename(columns={corr.index.name: "param1"}, inplace=True)

            heat = alt.Chart(corr_reset).mark_rect().encode(
                x=alt.X("param1:N", sort=list(dfp.columns)),
                y=alt.Y("param2:N", sort=list(dfp.columns)),
                tooltip=["param1","param2", alt.Tooltip("corr:Q", format=".2f")],
                color=alt.Color("corr:Q", scale=alt.Scale(scheme="redblue"), title="ρ")
            ).properties(height=360)
            st.altair_chart(heat, use_container_width=True)

            c1, c2 = st.columns(2)
            with c1:
                pX = st.selectbox("Parâmetro (eixo X)", list(dfp.columns))
            with c2:
                pY = st.selectbox("Parâmetro (eixo Y)", [c for c in dfp.columns if c != pX])

            scat = (dfp[[pX,pY]].dropna().reset_index()
                    .rename(columns={pX:"x", pY:"y"}))
            sc = alt.Chart(scat).mark_circle().encode(
                x=alt.X("x:Q", title=pX),
                y=alt.Y("y:Q", title=pY),
                tooltip=["date:T","x:Q","y:Q"]
            ).properties(height=360).interactive()
            st.altair_chart(sc, use_container_width=True)

# --- Export
st.download_button(
    "⬇️ Baixar CSV filtrado (seleção atual)",
    data.to_csv(index=False).encode("utf-8"),
    file_name="dashboard_selecao.csv",
    mime="text/csv",
)

st.markdown('<div class="footer">© DAP Sistemas Espaciais · Demo POC · Folium + Esri Tiles.</div>', unsafe_allow_html=True)
