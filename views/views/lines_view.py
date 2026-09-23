# views/lines_view.py
# Betta Farm Management System
# Session 21 — Line & Variety health dashboard.

import streamlit as st

from modules.line_health import compute_line_health, compute_variety_health


# ============================================================
# RENDER HELPERS
# ============================================================

def _render_warning_badge(warning: dict):
    kind = warning.get("kind", "warning")
    icon = warning.get("icon", "⚠️")
    label = warning.get("label", "Warning")
    reason = warning.get("reason", "")

    if kind == "declining":
        st.error(f"{icon} **{label}** — {reason}")
    elif kind == "stagnant":
        st.warning(f"{icon} **{label}** — {reason}")
    else:
        st.info(f"{icon} **{label}** — {reason}")


def _render_generation_breakdown(generations: dict):
    """Renders P1×N · F1×N · F2×N ... as a single caption line."""
    if not generations:
        st.caption("No generations recorded.")
        return

    # Sort: P1, F1, F2, F3+, others
    def sort_key(gen):
        if gen == "P1":
            return (0, 0)
        if gen.startswith("F") and gen[1:].rstrip("+").isdigit():
            return (1, int(gen[1:].rstrip("+")))
        return (2, 0)

    parts = []
    for gen in sorted(generations.keys(), key=sort_key):
        parts.append(f"**{gen}**×{generations[gen]}")
    st.caption(" · ".join(parts))


def _render_line_card(entry: dict, *, is_unassigned: bool = False):
    code = entry.get("line_code") or "?"
    stats = entry.get("stats") or {}

    title = f"### 🧬 Line `{code}`"
    if is_unassigned:
        title = f"### ❔ Unassigned (`{code}`)"

    with st.container(border=True):
        st.markdown(title)

        # Population + breeders
        col_a, col_b, col_c = st.columns(3)
        col_a.metric("Total Fish", stats.get("total_fish", 0))
        col_b.metric("Breeders", stats.get("total_breeders", 0))
        col_c.metric(
            "M / F",
            f"{stats.get('male_breeders', 0)} / {stats.get('female_breeders', 0)}",
        )

        # Generations
        st.markdown("**Generations**")
        _render_generation_breakdown(stats.get("generations") or {})

        # Spawns + Survival
        col_d, col_e, col_f = st.columns(3)
        total_spawns = stats.get("total_spawns", 0)
        active = stats.get("active_spawns", 0)
        col_d.metric("Spawns", total_spawns)
        col_e.metric("Active", active)

        sr = stats.get("success_rate")
        col_f.metric("Success Rate", f"{sr:.0f}%" if sr is not None else "—")

        col_g, col_h = st.columns(2)
        surv = stats.get("survival_avg")
        col_g.metric("Avg Survival", f"{surv * 100:.0f}%" if surv is not None else "—")
        form = stats.get("form_avg")
        col_h.metric("Avg Form Score", f"{form:.0f}" if form is not None else "—")

        # Warnings
        warnings = stats.get("warnings") or []
        for w in warnings:
            _render_warning_badge(w)

        # Hint for unassigned
        if is_unassigned and stats.get("total_fish", 0) > 0:
            st.caption(
                "💡 Assign a **line_code** to these fish (in Fish Registry → Manage) "
                "to track them as a real line."
            )


def _render_variety_card(entry: dict):
    variety = entry.get("variety") or "Unspecified"
    stats = entry.get("stats") or {}

    with st.container(border=True):
        st.markdown(f"### 🎨 {variety}")

        col_a, col_b, col_c, col_d = st.columns(4)
        col_a.metric("Total Fish", stats.get("total_fish", 0))
        col_b.metric("Breeders", stats.get("total_breeders", 0))
        col_c.metric(
            "M / F",
            f"{stats.get('male_breeders', 0)} / {stats.get('female_breeders', 0)}",
        )
        col_d.metric("Active Spawns", stats.get("active_spawns", 0))


# ============================================================
# TAB RENDERERS
# ============================================================

def render_by_line_tab():
    st.caption(
        "Fish grouped by their **line_code** — your own developed lines. "
        "Fish with no code appear under Unassigned."
    )

    entries = compute_line_health()
    if not entries:
        st.info("No fish registered yet.")
        return

    real_lines = [e for e in entries if not e.get("is_unassigned")]
    unassigned = [e for e in entries if e.get("is_unassigned")]

    if not real_lines and not unassigned:
        st.info("No lines to show.")
        return

    # Summary
    col_a, col_b, col_c = st.columns(3)
    col_a.metric("Active Lines", len(real_lines))
    col_b.metric(
        "Total fish in lines",
        sum(e["stats"]["total_fish"] for e in real_lines),
    )
    col_c.metric(
        "Unassigned fish",
        sum(e["stats"]["total_fish"] for e in unassigned),
    )

    st.markdown("---")

    # Real lines first
    for entry in real_lines:
        _render_line_card(entry, is_unassigned=False)

    # Unassigned at the bottom
    for entry in unassigned:
        _render_line_card(entry, is_unassigned=True)


def render_by_variety_tab():
    st.caption(
        "Fish grouped by **variety** (Avatar, Red Dragon, etc.). "
        "Lightweight overview."
    )

    entries = compute_variety_health()
    if not entries:
        st.info("No fish registered yet.")
        return

    st.markdown("---")
    for entry in entries:
        _render_variety_card(entry)


# ============================================================
# PAGE
# ============================================================

def render_lines_page():
    st.title("🧬 Lines & Varieties")
    st.caption("Health overview of your breeding lines and varieties.")

    tab1, tab2 = st.tabs(["🧬 By Line Code", "🎨 By Variety"])

    with tab1:
        render_by_line_tab()

    with tab2:
        render_by_variety_tab()


def render_lines():
    """Alias entrypoint."""
    render_lines_page()
