"""Streamlit web UI for browsing rental listings."""
from __future__ import annotations

import json
import math

import streamlit as st
import streamlit.components.v1 as components

from house_search.models import Listing
from house_search.storage import load_listings, update_listing_status

# Santiago de Compostela centre
_CENTRE = (42.8782, -8.5448)
_SOURCE_COLOURS = {
    "idealista":   "#2563eb",   # blue
    "fotocasa":    "#ea580c",   # orange
    "milanuncios": "#16a34a",   # green
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _filter_listings(
    listings: list[Listing],
    price_range: tuple[float, float],
    price_max_cap: float,
    ppr_range: tuple[float, float],
    ppr_max_cap: float,
    min_rooms: int,
    max_rooms: int,
    min_size: float,
    max_size: float,
    size_max_cap: float,
    amenities: dict[str, bool],
    sources: list[str],
    property_types: list[str],
    statuses: list[str],
) -> list[Listing]:
    result = []
    for lst in listings:
        if statuses and lst.status not in statuses:
            continue
        # When slider is at its cap, treat as "no upper bound"
        price_max = math.inf if price_range[1] >= price_max_cap else price_range[1]
        if not (price_range[0] <= lst.price <= price_max):
            continue
        ppr = lst.price_per_room
        if ppr is not None:
            ppr_max = math.inf if ppr_range[1] >= ppr_max_cap else ppr_range[1]
            if not (ppr_range[0] <= ppr <= ppr_max):
                continue
        if lst.rooms is not None and not (min_rooms <= lst.rooms <= max_rooms):
            continue
        if lst.size_m2 is not None:
            size_max = math.inf if max_size >= size_max_cap else max_size
            if not (min_size <= lst.size_m2 <= size_max):
                continue
        if sources and lst.source not in sources:
            continue
        if property_types and lst.property_type not in property_types:
            continue
        for attr, required in amenities.items():
            if required:
                val = getattr(lst, attr)
                if val is not True:
                    break
        else:
            result.append(lst)
    return result


def _render_map(listings: list[Listing], highlighted_id: str | None = None) -> None:
    """Render an interactive Leaflet map, optionally highlighting one marker."""
    markers_data = [
        {
            "id": lst.id,
            "lat": lst.latitude,
            "lon": lst.longitude,
            "title": lst.title[:60],
            "price": lst.price,
            "source": lst.source,
            "url": lst.url,
            "rooms": lst.rooms,
            "size_m2": lst.size_m2,
            "price_per_room": lst.price_per_room,
            "highlighted": lst.id == highlighted_id,
        }
        for lst in listings
        if lst.latitude is not None and lst.longitude is not None
    ]

    html = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8"/>
  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
  <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
  <style>
    html, body {{ margin:0; padding:0; height:100%; }}
    #map {{ width:100%; height:100%; }}
  </style>
</head>
<body>
<div id="map"></div>
<script>
const DATA = {json.dumps(markers_data)};
const COLOURS = {json.dumps(_SOURCE_COLOURS)};
const DEFAULT_COL = '#6b7280';
const HIGHLIGHT_COL = '#f59e0b';

let centre = [{_CENTRE[0]},{_CENTRE[1]}];
let zoom = 13;
const highlighted = DATA.find(d => d.highlighted);
if (highlighted) {{ centre = [highlighted.lat, highlighted.lon]; zoom = 15; }}

const map = L.map('map').setView(centre, zoom);
L.tileLayer('https://{{s}}.basemaps.cartocdn.com/light_all/{{z}}/{{x}}/{{y}}{{r}}.png', {{
  attribution: '&copy; OpenStreetMap &copy; CARTO', maxZoom: 19
}}).addTo(map);

DATA.forEach(d => {{
  const col  = d.highlighted ? HIGHLIGHT_COL : (COLOURS[d.source] || DEFAULT_COL);
  const ppr  = d.price_per_room ? ` &middot; ${{Math.round(d.price_per_room)}}€/h` : '';
  const rooms = d.rooms   ? ` &middot; ${{d.rooms}}h`               : '';
  const size  = d.size_m2 ? ` &middot; ${{Math.round(d.size_m2)}}m²` : '';
  const m = L.circleMarker([d.lat, d.lon], {{
    radius: d.highlighted ? 14 : 7,
    color: col, fillColor: col,
    fillOpacity: d.highlighted ? 1.0 : 0.7,
    weight: d.highlighted ? 3 : 2,
  }}).addTo(map).bindPopup(
    `<b><a href="${{d.url}}" target="_blank">${{d.title}}</a></b><br>` +
    `<span style="color:${{col}}">${{Math.round(d.price)}}€/mes</span>${{rooms}}${{size}}${{ppr}}`
  );
  if (d.highlighted) m.openPopup();
}});
</script>
</body>
</html>"""
    components.html(html, height=600)


_STATUS_LABELS = {
    "new": ("⬜", "Nueva"),
    "to_call": ("📞", "Llamar"),
    "called": ("✅", "Llamada"),
    "discarded": ("🗑️", "Descartada"),
}

_NEXT_ACTIONS = {
    "new":       [("📞 Llamar", "to_call"), ("🗑️ Descartar", "discarded")],
    "to_call":   [("✅ Llamada", "called"), ("🗑️ Descartar", "discarded"), ("↩️", "new")],
    "called":    [("📞 Volver a llamar", "to_call"), ("🗑️ Descartar", "discarded"), ("↩️", "new")],
    "discarded": [("↩️ Restaurar", "new")],
}


def _set_status(listing_id: str, status: str) -> None:
    update_listing_status(listing_id, status)
    _load.clear()


def _listing_card(lst: Listing) -> None:
    ppr = f" · **{lst.price_per_room:.0f}€/h**" if lst.price_per_room else ""
    rooms = f" · {lst.rooms}h" if lst.rooms else ""
    size = f" · {lst.size_m2:.0f}m²" if lst.size_m2 else ""
    source_badge = _SOURCE_COLOURS.get(lst.source, "#6b7280")
    badges = []
    if lst.has_elevator:
        badges.append("🛗")
    if lst.has_parking:
        badges.append("🅿️")
    if lst.has_terrace:
        badges.append("🌿")

    status_icon, status_label = _STATUS_LABELS.get(lst.status, ("⬜", lst.status))
    is_highlighted = st.session_state.get("map_highlight") == lst.id

    with st.container(border=True):
        cols = st.columns([2, 5])
        with cols[0]:
            if lst.image_urls:
                st.image(lst.image_urls[0], use_container_width=True)
            else:
                st.markdown("🏠")
        with cols[1]:
            st.markdown(
                f'<span style="display:inline-block;width:10px;height:10px;'
                f'border-radius:50%;background:{source_badge};margin-right:4px"></span>'
                f'[{lst.title[:55]}]({lst.url})',
                unsafe_allow_html=True,
            )
            st.markdown(
                f"**{lst.price:.0f}€/mes**{ppr}{rooms}{size}"
                + ("  " + " ".join(badges) if badges else "")
            )
            if lst.neighborhood:
                st.caption(lst.neighborhood)
            if lst.phone:
                st.markdown(f"📞 `{lst.phone}`")

        action_cols = st.columns([1, 2] + [2] * len(_NEXT_ACTIONS.get(lst.status, [])))
        with action_cols[0]:
            locate_label = "🟡" if is_highlighted else "📍"
            if lst.latitude and st.button(locate_label, key=f"locate_{lst.id}", help="Ver en el mapa"):
                st.session_state.map_highlight = None if is_highlighted else lst.id
                st.rerun()
        with action_cols[1]:
            st.caption(f"{status_icon} {status_label}")
        for i, (label, new_status) in enumerate(_NEXT_ACTIONS.get(lst.status, []), 2):
            with action_cols[i]:
                if st.button(label, key=f"status_{lst.id}_{new_status}", use_container_width=True):
                    _set_status(lst.id, new_status)
                    st.rerun()


# ---------------------------------------------------------------------------
# Main app
# ---------------------------------------------------------------------------

@st.cache_data(ttl=60)
def _load() -> list[Listing]:
    return load_listings()


def main() -> None:
    st.set_page_config(
        page_title="House Search · Santiago de Compostela",
        page_icon="🏠",
        layout="wide",
    )
    st.title("🏠 Alquiler en Santiago de Compostela")

    all_listings = _load()
    if not all_listings:
        st.warning("No listings found. Run `house-search scrape` first.")
        return

    # ---- compute bounds for sliders ----
    def _p99(values: list[float]) -> float:
        s = sorted(values)
        return s[min(int(len(s) * 0.99), len(s) - 1)]

    prices = [l.price for l in all_listings]
    pprs = [l.price_per_room for l in all_listings if l.price_per_room is not None]
    sizes = [l.size_m2 for l in all_listings if l.size_m2 is not None]
    all_rooms = [l.rooms for l in all_listings if l.rooms is not None]
    all_neighborhoods = sorted({l.neighborhood for l in all_listings if l.neighborhood})

    min_price = math.floor(min(prices))
    max_price = math.ceil(_p99(prices))
    min_ppr = math.floor(min(pprs)) if pprs else 0
    max_ppr = math.ceil(_p99(pprs)) if pprs else 2000
    min_size_val = math.floor(min(sizes)) if sizes else 0
    max_size_val = math.ceil(_p99(sizes)) if sizes else 500
    min_rooms_val = min(all_rooms) if all_rooms else 1
    max_rooms_val = max(all_rooms) if all_rooms else 6

    # ---- sidebar filters ----
    with st.sidebar:
        st.header("Filtros")

        price_range = st.slider(
            "Precio mensual (€)", min_price, max_price,
            (min_price, max_price), step=50,
        )

        if pprs:
            ppr_range: tuple[float, float] = st.slider(
                "Precio por habitación (€/h)", min_ppr, max_ppr,
                (min_ppr, max_ppr), step=25,
            )
        else:
            ppr_range = (0, 99999)

        room_range = st.slider(
            "Habitaciones", min_rooms_val, max(max_rooms_val, 5),
            (min_rooms_val, max(max_rooms_val, 5)),
        )

        if sizes:
            size_range = st.slider(
                "Superficie (m²)", min_size_val, max_size_val,
                (min_size_val, max_size_val), step=5,
            )
        else:
            size_range = (0, 9999)

        st.subheader("Extras")
        want_elevator = st.checkbox("Ascensor")
        want_parking = st.checkbox("Parking / Garaje")
        want_terrace = st.checkbox("Terraza")

        st.subheader("Fuente")
        all_sources = sorted({l.source for l in all_listings})
        selected_sources = [
            src for src in all_sources
            if st.checkbox(src.capitalize(), value=True, key=f"src_{src}")
        ]

        st.subheader("Estado")
        show_new = st.checkbox("⬜ Nueva", value=True)
        show_to_call = st.checkbox("📞 Llamar", value=True)
        show_called = st.checkbox("✅ Llamada", value=True)
        show_discarded = st.checkbox("🗑️ Descartada", value=False)

        st.subheader("Tipo de inmueble")
        all_types = sorted({l.property_type for l in all_listings})
        selected_types = st.multiselect("Tipo", all_types, default=all_types)

        if all_neighborhoods:
            st.subheader("Barrio")
            selected_hoods = st.multiselect(
                "Barrio / Zona", all_neighborhoods, default=all_neighborhoods
            )
        else:
            selected_hoods = []

    # ---- apply filters ----
    statuses_filter = []
    if show_new:
        statuses_filter.append("new")
    if show_to_call:
        statuses_filter.append("to_call")
    if show_called:
        statuses_filter.append("called")
    if show_discarded:
        statuses_filter.append("discarded")

    amenities = {
        "has_elevator": want_elevator,
        "has_parking": want_parking,
        "has_terrace": want_terrace,
    }

    filtered = _filter_listings(
        all_listings,
        price_range=price_range,
        price_max_cap=max_price,
        ppr_range=ppr_range,
        ppr_max_cap=max_ppr,
        min_rooms=room_range[0],
        max_rooms=room_range[1],
        min_size=size_range[0],
        max_size=size_range[1],
        size_max_cap=max_size_val,
        amenities=amenities,
        sources=selected_sources,
        property_types=selected_types,
        statuses=statuses_filter,
    )

    if selected_hoods:
        filtered = [l for l in filtered if l.neighborhood in selected_hoods]

    filtered.sort(key=lambda l: l.price)

    # ---- layout: cards | map ----
    st.caption(
        f"Mostrando **{len(filtered)}** de {len(all_listings)} anuncios  "
        f"· {sum(1 for l in filtered if l.latitude is not None)} en el mapa"
    )

    col_list, col_map = st.columns([4, 6])

    highlighted_id: str | None = st.session_state.get("map_highlight")

    with col_map:
        _render_map(filtered, highlighted_id=highlighted_id)

    with col_list:
        if not filtered:
            st.info("No hay anuncios con los filtros actuales.")
        else:
            for lst in filtered:
                _listing_card(lst)


if __name__ == "__main__":
    main()
