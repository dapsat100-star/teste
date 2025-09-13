
import io
from pathlib import Path
from typing import Dict, List, Tuple, Optional
from urllib.parse import quote

import numpy as np
import pandas as pd
import streamlit as st
import matplotlib.pyplot as plt

# ===================== CONFIGURE AQUI =====================
DEFAULT_BASE_URL = "https://raw.githubusercontent.com/dapsat100-star/geoportal/main"
# =========================================================

try:
    import folium
    from streamlit_folium import st_folium
    HAVE_MAP = True
except Exception:
    HAVE_MAP = False

st.set_page_config(page_title="Geoportal — Pro (Séries avançadas)", layout="wide")
st.title("📷 Geoportal de Metano — Painel Pro (Séries e Estatística)")

with st.sidebar:
    st.header("📁 Suba o Excel")
    uploaded = st.file_uploader("Upload do Excel (.xlsx)", type=["xlsx"])
    st.caption(f"As URLs das figuras serão montadas como `{DEFAULT_BASE_URL}/images/<arquivo>`.")
    st.markdown("---")
    st.caption("Dica: mantenha `images/` em minúsculo.")

@st.cache_data
def read_excel_from_bytes(file_bytes) -> Dict[str, pd.DataFrame]:
    xls = pd.ExcelFile(file_bytes, engine="openpyxl")
    return {sn: pd.read_excel(xls, sheet_name=sn, engine="openpyxl") for sn in xls.sheet_names}

def normalize_cols(df: pd.DataFrame) -> pd.DataFrame:
    cols = list(df.columns)
    if cols: cols[0] = "Parametro"
    normed = []
    for c in cols:
        s = str(c).strip()
        if s.lower() in ("lat","latitude"): normed.append("Lat")
        elif s.lower() in ("long","lon","longitude"): normed.append("Long")
        else: normed.append(s)
    df.columns = normed
    return df

def extract_dates_from_first_row(df: pd.DataFrame) -> Tuple[List[str], Dict[str, str], List[pd.Timestamp]]:
    cols = list(df.columns)
    try:
        data_idx = cols.index("Data")
    except ValueError:
        data_idx = 3 if len(cols) > 3 else 0
    date_cols = cols[data_idx:]
    pretty = {}
    dates_ts = []
    for c in date_cols:
        v = df.loc[0, c] if 0 in df.index else None
        label, ts = None, pd.NaT
        if pd.notna(v):
            for dayfirst in (True, False):
                try:
                    dt = pd.to_datetime(v, dayfirst=dayfirst, errors="raise")
                    label = dt.strftime("%Y-%m-%d")
                    ts = pd.to_datetime(label)
                    break
                except Exception:
                    pass
        if not label:
            try:
                dt = pd.to_datetime(str(c), dayfirst=True, errors="raise")
                label = dt.strftime("%Y-%m")
                ts = pd.to_datetime(label + "-01", errors="coerce")
            except Exception:
                label = str(c)
                ts = pd.NaT
        pretty[c] = label
        dates_ts.append(ts)
    return date_cols, pretty, dates_ts

def build_record_for_month(df: pd.DataFrame, date_col: str) -> Dict[str, Optional[str]]:
    dfi = df.copy()
    if dfi.columns[0] != "Parametro":
        dfi.columns = ["Parametro"] + list(dfi.columns[1:])
    dfi["Parametro"] = dfi["Parametro"].astype(str).str.strip()
    dfi = dfi.set_index("Parametro", drop=True)
    rec = {param: dfi.loc[param, date_col] for param in dfi.index}
    lat_val = df["Lat"].dropna().iloc[0] if "Lat" in df.columns and df["Lat"].notna().any() else None
    lon_val = df["Long"].dropna().iloc[0] if "Long" in df.columns and df["Long"].notna().any() else None
    rec["_lat"] = lat_val
    rec["_long"] = lon_val
    return rec

def resolve_image_target(path_str: str) -> Optional[str]:
    if path_str is None or (isinstance(path_str, float) and pd.isna(path_str)):
        return None
    s = str(path_str).strip()
    if not s: return None
    s = s.replace("\\","/")
    if s.startswith("./"): s = s[2:]
    if s.lower().startswith(("http://","https://")): return s
    return f"{DEFAULT_BASE_URL.rstrip('/')}/{s.lstrip('/')}"

# --- Helpers Série Temporal ---
def extract_series(dfi: pd.DataFrame, date_cols_sorted, dates_ts_sorted, row_name="Taxa Metano"):
    idx_map = {i.lower(): i for i in dfi.index}
    key = idx_map.get(row_name.lower())
    rows = []
    if key is not None:
        for i, col in enumerate(date_cols_sorted):
            val = dfi.loc[key, col] if col in dfi.columns else None
            try:
                num = float(pd.to_numeric(val))
            except Exception:
                num = None
            ts = dates_ts_sorted[i]
            if pd.notna(num) and pd.notna(ts):
                rows.append({"date": ts, "value": float(num)})
    s = pd.DataFrame(rows)
    if not s.empty:
        s = s.sort_values("date").reset_index(drop=True)
    return s

def resample_series(s: pd.DataFrame, freq: str, agg: str):
    if s.empty: return s
    s2 = s.set_index("date").asfreq("D")  # dia a dia, preenchendo buracos como NaN
    # agregação por frequência desejada
    if agg == "média": agg_fn = "mean"
    elif agg == "mediana": agg_fn = "median"
    elif agg == "máx": agg_fn = "max"
    elif agg == "mín": agg_fn = "min"
    else: agg_fn = "mean"
    s3 = getattr(s2.resample(freq), agg_fn)()
    s3 = s3.dropna()
    s3 = s3.reset_index().rename(columns={"date":"date"})
    return s3

def smooth_series(s: pd.DataFrame, method: str, window: int):
    if s.empty: return s, None
    sc = s.copy()
    if method == "Nenhuma":
        sc["smooth"] = sc["value"]
    elif method == "Média móvel":
        sc["smooth"] = sc["value"].rolling(window=window, min_periods=1).mean()
    elif method == "Exponencial (EMA)":
        sc["smooth"] = sc["value"].ewm(span=window, adjust=False).mean()
    else:
        sc["smooth"] = sc["value"]
    return sc, sc["smooth"].std() if "smooth" in sc else None

def filter_outliers(s: pd.DataFrame, method: str):
    if s.empty: return s
    sc = s.copy()
    if method == "Nenhum":
        return sc
    if method == "Z-score>3":
        z = (sc["value"] - sc["value"].mean()) / (sc["value"].std(ddof=0) + 1e-9)
        sc = sc[abs(z) <= 3.0]
    elif method == "IQR":
        q1, q3 = sc["value"].quantile(0.25), sc["value"].quantile(0.75)
        iqr = q3 - q1
        lower, upper = q1 - 1.5*iqr, q3 + 1.5*iqr
        sc = sc[(sc["value"] >= lower) & (sc["value"] <= upper)]
    return sc

def trendline(x: np.ndarray, y: np.ndarray):
    if len(x) < 2: return None
    coeffs = np.polyfit(x, y, 1)
    line = np.poly1d(coeffs)
    return coeffs, line

# === Fluxo principal ===
if uploaded is None:
    st.info("Faça o upload do seu Excel (`.xlsx`) no painel lateral.")
    st.stop()

try:
    book = read_excel_from_bytes(uploaded)
except Exception as e:
    st.error(f"Falha ao ler o Excel enviado. Detalhe: {e}")
    st.stop()

book = {name: normalize_cols(df.copy()) for name, df in book.items()}

# Seleção de site
site = st.selectbox("Selecione o Site", sorted(book.keys()))
df_site = book[site]
date_cols, pretty, dates_ts = extract_dates_from_first_row(df_site)
order_idx = sorted(range(len(date_cols)), key=lambda i: (pd.Timestamp.min if pd.isna(dates_ts[i]) else dates_ts[i]))
date_cols_sorted = [date_cols[i] for i in order_idx]
labels_sorted = [pretty[date_cols[i]] for i in order_idx]
dates_ts_sorted = [dates_ts[i] for i in order_idx]

# Seleção da data exibida na imagem
selected_label = st.selectbox("Selecione a data", labels_sorted)
selected_col = date_cols_sorted[labels_sorted.index(selected_label)]

# ------------------- Painel Superior (Imagem + KPIs) -------------------
left, right = st.columns([2,1])

with left:
    rec = build_record_for_month(df_site, selected_col)
    img = resolve_image_target(rec.get("Imagem"))
    st.subheader(f"Imagem — {site} — {selected_label}")
    if img:
        st.image(img, use_container_width=True)
    else:
        st.error("Imagem não encontrada para essa data.")

    if HAVE_MAP and (rec.get("_lat") is not None and rec.get("_long") is not None):
        with st.expander("🗺️ Mostrar mapa (opcional)", expanded=False):
            m = folium.Map(location=[float(rec["_lat"]), float(rec["_long"])], zoom_start=13, tiles="OpenStreetMap")
            folium.Marker([float(rec["_lat"]), float(rec["_long"])], tooltip=site).add_to(m)
            st_folium(m, height=400, use_container_width=True)

with right:
    st.subheader("Detalhes do Registro")
    dfi = df_site.copy()
    if dfi.columns[0] != "Parametro":
        dfi.columns = ["Parametro"] + list(dfi.columns[1:])
    dfi["Parametro"] = dfi["Parametro"].astype(str).str.strip()
    dfi = dfi.set_index("Parametro", drop=True)

    def getv(name):
        for cand in (name, name.capitalize(), name.title(), name.replace("ç","c").replace("á","a")):
            if cand in dfi.index:
                return dfi.loc[cand, selected_col]
        return None
    k1, k2, k3 = st.columns(3)
    k1.metric("Taxa Metano", f"{getv('Taxa Metano')}" if pd.notna(getv('Taxa Metano')) else "—")
    k2.metric("Incerteza", f"{getv('Incerteza')}" if pd.notna(getv('Incerteza')) else "—")
    k3.metric("Vento", f"{getv('Velocidade do Vento')}" if pd.notna(getv('Velocidade do Vento')) else "—")

    st.markdown("---")
    st.caption("Tabela completa (parâmetro → valor):")
    show_df = dfi[[selected_col]].copy()
    show_df.columns = ["Valor"]
    if "Imagem" in show_df.index: show_df = show_df.drop(index="Imagem")
    show_df = show_df.applymap(lambda v: "" if (pd.isna(v)) else str(v))
    st.dataframe(show_df, use_container_width=True)

# ------------------- Painel Estatístico Avançado -------------------
st.markdown("### 🧪 Série temporal (ferramentas estatísticas)")

c1, c2, c3 = st.columns(3)
with c1:
    freq = st.selectbox("Frequência", ["Diário","Semanal","Mensal","Trimestral"], index=1)
with c2:
    smooth = st.selectbox("Suavização", ["Nenhuma","Média móvel","Exponencial (EMA)"])
with c3:
    out_filter = st.selectbox("Filtro de outliers", ["Nenhum","Z-score>3","IQR"])

c4, c5, c6 = st.columns(3)
with c4:
    agg = st.selectbox("Agregação", ["média","mediana","máx","mín"])
with c5:
    window = st.slider("Janela/Span", min_value=3, max_value=60, value=7, step=1)
with c6:
    band_type = st.selectbox("Bandas", ["Nenhuma","±k·desvio","Percentis 10/90"])

k = st.slider("k (para banda de confiança)", min_value=1.0, max_value=4.0, value=2.0, step=0.25)

col_opts = st.columns(3)
with col_opts[0]:
    show_trend = st.checkbox("Mostrar tendência linear")
with col_opts[1]:
    normalize_base = st.checkbox("Normalizar pela linha base (primeira janela)")
with col_opts[2]:
    mark_anom = st.checkbox("Marcar anomalias (acima de banda)")

# Mapeia frequência
freq_map = {"Diário":"D","Semanal":"W","Mensal":"M","Trimestral":"Q"}
series_raw = extract_series(dfi, date_cols_sorted, dates_ts_sorted)
series = resample_series(series_raw, freq_map[freq], agg)
series = filter_outliers(series, out_filter)
series, sigma = smooth_series(series, smooth, window)

# Normalização opcional
if normalize_base and not series.empty:
    base = series["smooth"].iloc[:window].mean()
    if pd.notna(base) and base != 0:
        series["smooth"] = series["smooth"] / base

# Plot
fig, ax = plt.subplots()
ax.plot(series["date"], series["smooth"], marker="o", linewidth=2)
ax.set_xlabel("date"); ax.set_ylabel("Valor"); ax.grid(True, linestyle="--", alpha=0.3)

# Bandas
if band_type != "Nenhuma" and not series.empty:
    if band_type == "±k·desvio":
        mu = series["smooth"].mean()
        std = series["smooth"].std(ddof=0)
        upper = mu + k*std
        lower = mu - k*std
    else:  # Percentis 10/90
        lower = series["smooth"].quantile(0.10)
        upper = series["smooth"].quantile(0.90)
    ax.fill_between(series["date"], lower, upper, alpha=0.15)

# Tendência linear
if show_trend and not series.empty:
    x = (series["date"] - series["date"].min()).dt.days.values.astype(float)
    y = series["smooth"].values.astype(float)
    res = trendline(x, y)
    if res:
        coeffs, line = res
        ax.plot(series["date"], line(x), linestyle="--")

# Marcar anomalias
if mark_anom and band_type != "Nenhuma" and not series.empty:
    yy = series["smooth"]
    if band_type == "±k·desvio":
        mu = yy.mean(); std = yy.std(ddof=0); up = mu + k*std
    else:
        up = yy.quantile(0.90)
    anom = series[yy > up]
    ax.scatter(anom["date"], anom["smooth"], s=40)

# Rotulos
for t in ax.get_xticklabels():
    t.set_rotation(30); t.set_ha("right")

st.pyplot(fig)

# --- Boxplots por mês (um único gráfico limpo) ---
st.markdown("### Boxplots por mês + média mensal")
if not series_raw.empty:
    dfm = series_raw.copy()
    dfm["month"] = dfm["date"].dt.to_period("M").dt.to_timestamp()
    groups = dfm.groupby("month")["value"].apply(list).reset_index()
    months = groups["month"].tolist()
    positions = list(range(1, len(months)+1))
    means = [np.mean(v) if len(v)>0 else np.nan for v in groups["value"]]

    fig2, ax2 = plt.subplots()
    ax2.boxplot(groups["value"].tolist(), positions=positions)
    ax2.plot(positions, means, marker="o", linewidth=2)
    ax2.set_xlabel("Mês"); ax2.set_ylabel("Taxa de Metano")
    ax2.set_xticks(positions)
    ax2.set_xticklabels([m.strftime("%Y-%m") for m in months], rotation=30, ha="right")
    ax2.grid(True, linestyle="--", alpha=0.3)
    st.pyplot(fig2)
else:
    st.info("Sem dados suficientes para boxpl
