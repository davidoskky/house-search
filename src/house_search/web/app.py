"""Streamlit web UI for browsing rental listings."""
from __future__ import annotations

import math

import folium
import streamlit as st
from streamlit_folium import st_folium

from house_search.models import Listing
from house_search.storage import load_listings, update_listing_status

# Santiago de Compostela centre
_CENTRE = (42.8782, -8.5448)
_SOURCE_COLOURS = {
    "idealista": "#2563eb",   # blue
    "fotocasa": "#ea580c",    # orange
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _filter_listings(
    listings: list[Listing],
    price_range: tuple[float, float],
    ppr_range: tuple[float, float],
    min_rooms: int,
    max_rooms: int,
    min_size: float,
    max_size: float,
    amenities: dict[str, bool],
    sources: list[str],
    property_types: list[str],
    statuses: list[str],
) -> list[Listing]:
    result = []
    for lst in listings:
        if statuses and lst.status not in statuses:
            continue
        if not (price_range[0] <= lst.price <= price_range[1]):
            continue
        ppr = lst.price_per_room
        if ppr is not None and not (ppr_range[0] <= ppr <= ppr_range[1]):
            continue
        if lst.rooms is not None and not (min_rooms <= lst.rooms <= max_rooms):
            continue
        if lst.size_m2 is not None and not (min_size <= lst.size_m2 <= max_size):
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


def _build_map(listings: list[Listing]) -> folium.Map:
    m = folium.Map(location=_CENTRE, zoom_start=13, tiles="CartoDB positron")
    for lst in listings:
        if lst.latitude is None or lst.longitude is None:
            continue
        colour = _SOURCE_COLOURS.get(lst.source, "#6b7280")
        ppr = f"  ·  {lst.price_per_room:.0f}€/h" if lst.price_per_room else ""
        size = f"  ·  {lst.size_m2:.0f}m²" if lst.size_m2 else ""
        rooms = f"  ·  {lst.rooms}h" if lst.rooms else ""
        popup_html = (
            f"<b><a href='{lst.url}' target='_blank'>{lst.title[:60]}</a></b><br>"
            f"<b style='color:{colour}'>{lst.price:.0f}€/mes</b>"
            f"{rooms}{size}{ppr}"
        )
        folium.CircleMarker(
            location=(lst.latitude, lst.longitude),
            radius=7,
            color=colour,
            fill=True,
            fill_color=colour,
            fill_opacity=0.7,
            popup=folium.Popup(popup_html, max_width=280),
            tooltip=f"{lst.price:.0f}€ · {lst.source}",
        ).add_to(m)
    return m


_STATUS_LABELS = {
    "new": ("⬜", "Nueva"),
    "to_call": ("📞", "Llamar"),
    "called": ("✅", "Llamada"),
    "discarded": ("🗑️", "Descartada"),
}

_NEXT_ACTIONS = {
    # current_status -> list of (label, new_status)
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
    geo = "📍" if lst.latitude else "·"
    source_badge = "🔵" if lst.source == "idealista" else "🟠"
    badges = []
    if lst.has_elevator:
        badges.append("🛗")
    if lst.has_parking:
        badges.append("🅿️")
    if lst.has_terrace:
        badges.append("🌿")

    status_icon, status_label = _STATUS_LABELS.get(lst.status, ("⬜", lst.status))

    with st.container(border=True):
        cols = st.columns([2, 5])
        with cols[0]:
            if lst.image_urls:
                st.image(lst.image_urls[0], use_container_width=True)
            else:
                st.markdown("🏠")
        with cols[1]:
            st.markdown(f"{source_badge} {geo} [{lst.title[:55]}]({lst.url})")
            st.markdown(
                f"**{lst.price:.0f}€/mes**{ppr}{rooms}{size}"
                + ("  " + " ".join(badges) if badges else "")
            )
            if lst.neighborhood:
                st.caption(lst.neighborhood)
            if lst.phone:
                st.markdown(f"📞 `{lst.phone}`")

        # Status row: current status badge + action buttons
        action_cols = st.columns([2] + [2] * len(_NEXT_ACTIONS.get(lst.status, [])))
        with action_cols[0]:
            st.caption(f"{status_icon} {status_label}")
        for i, (label, new_status) in enumerate(_NEXT_ACTIONS.get(lst.status, []), 1):
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
    prices = [l.price for l in all_listings]
    pprs = [l.price_per_room for l in all_listings if l.price_per_room is not None]
    sizes = [l.size_m2 for l in all_listings if l.size_m2 is not None]
    all_rooms = [l.rooms for l in all_listings if l.rooms is not None]
    all_neighborhoods = sorted({l.neighborhood for l in all_listings if l.neighborhood})

    min_price, max_price = math.floor(min(prices)), math.ceil(max(prices))
    min_ppr = math.floor(min(pprs)) if pprs else 0
    max_ppr = math.ceil(max(pprs)) if pprs else 2000
    min_size_val = math.floor(min(sizes)) if sizes else 0
    max_size_val = math.ceil(max(sizes)) if sizes else 500
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
        show_idealista = st.checkbox("Idealista", value=True)
        show_fotocasa = st.checkbox("Fotocasa", value=True)

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
    sources_filter = []
    if show_idealista:
        sources_filter.append("idealista")
    if show_fotocasa:
        sources_filter.append("fotocasa")

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
        ppr_range=ppr_range,
        min_rooms=room_range[0],
        max_rooms=room_range[1],
        min_size=size_range[0],
        max_size=size_range[1],
        amenities=amenities,
        sources=sources_filter,
        property_types=selected_types,
        statuses=statuses_filter,
    )

    # Apply neighborhood filter (post-step, cleaner)
    if selected_hoods:
        filtered = [l for l in filtered if l.neighborhood in selected_hoods]

    # Sort by price
    filtered.sort(key=lambda l: l.price)

    # ---- layout: cards | map ----
    st.caption(
        f"Mostrando **{len(filtered)}** de {len(all_listings)} anuncios  "
        f"· {sum(1 for l in filtered if l.latitude is not None)} en el mapa"
    )

    col_list, col_map = st.columns([4, 6])

    with col_map:
        m = _build_map(filtered)
        st_folium(m, width=None, height=600, returned_objects=[])

    with col_list:
        if not filtered:
            st.info("No hay anuncios con los filtros actuales.")
        else:
            for lst in filtered:
                _listing_card(lst)


if __name__ == "__main__":
    main()
