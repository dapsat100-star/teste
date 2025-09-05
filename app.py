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

        # URL com query param para forçar troca de fonte
        esri_url = (
            f"https://server.arcgisonline.com/ArcGIS/rest/services/"
            f"{bm_id}/MapServer/tile/{{z}}/{{y}}/{{x}}?fresh={bm_id}"
        )

        esri_layer = pdk.Layer(
            "TileLayer",
            id=f"esri-{bm_id}",          # muda quando você troca o basemap
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
                id=f"heat-{bm_id}",       # id também muda com o basemap
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
            map_style=None,              # garante que o Mapbox não interfira
        )
        st.pydeck_chart(deck, key=f"deck-{bm_id}")  # key muda quando troca o basemap
