# views/inheritance_view.py
# Betta Farm Management System
# Session 25 — Inheritance analysis UI.
# Tabs: Pair Leaderboard | Grades | Body Shape | Fin Checks

import pandas as pd
import plotly.express as px
import streamlit as st

from modules.inheritance import (
    compute_pair_leaderboard,
    compute_grade_inheritance_matrix,
    compute_body_shape_inheritance,
    compute_fin_check_inheritance,
    get_inheritance_summary,
    GRADE_ORDER,
    MIN_OFFSPRING_FOR_ANALYSIS,
)


# ============================================================
# HELPERS
# ============================================================

def _fmt_score(val) -> str:
    if val is None:
        return "—"
    try:
        return f"{float(val):.0f}"
    except (ValueError, TypeError):
        return "—"


def _fmt_delta(val) -> str:
    if val is None:
        return "—"
    try:
        d = float(val)
    except (ValueError, TypeError):
        return "—"
    if d > 2:
        return f"🟢 +{d:.0f}"
    if d < -2:
        return f"🔴 {d:.0f}"
    return f"⚪ {d:+.0f}"


def _grade_badge(grade: str) -> str:
    colors = {
        "Show Grade": ("#FFD700", "#4A3800"),
        "High Grade": ("#C0C0C0", "#333333"),
        "Breeder Grade": ("#CD7F32", "#FFFFFF"),
        "Material Grade": ("#9CA3AF", "#FFFFFF"),
        "Pet Grade": ("#E5E7EB", "#1F2937"),
    }
    bg, fg = colors.get(grade, ("#F3F4F6", "#374151"))
    return (
        f'<span style="display:inline-block;background:{bg};color:{fg};'
        f'font-size:11px;font-weight:600;padding:2px 8px;border-radius:10px;">'
        f'{grade or "—"}</span>'
    )


def _render_empty_state():
    st.warning(
        f"**Not enough data yet.** Inheritance analysis needs at least "
        f"**{MIN_OFFSPRING_FOR_ANALYSIS} jarred offspring** per spawn (currently, "
        f"either no jarred fish exist, or they came from spawns with too few to be statistically meaningful)."
    )
    st.info(
        "💡 **How to build data:**\n"
        f"1. **Jar** at least {MIN_OFFSPRING_FOR_ANALYSIS} fish from a spawn "
        "(Fry Batch Tracking → Jar Fry)\n"
        "2. **Grade** each jarred fish (Fish Registry → Manage)\n"
        "3. Come back here — the analytics will populate automatically"
    )


# ============================================================
# TAB 1: PAIR LEADERBOARD
# ============================================================

def _render_pair_leaderboard():
    st.caption(
        "Ranked list of parent pairs by average offspring form score. "
        "**Delta** shows whether offspring improved over their parents."
    )

    leaderboard = compute_pair_leaderboard()

    if not leaderboard:
        _render_empty_state()
        return

    st.caption(f"**{len(leaderboard)}** pair-spawn records with ≥ {MIN_OFFSPRING_FOR_ANALYSIS} jarred offspring.")

    # Summary metrics
    deltas = [d["delta"] for d in leaderboard if d["delta"] is not None]
    improving = sum(1 for d in deltas if d > 2)
    declining = sum(1 for d in deltas if d < -2)

    col1, col2, col3 = st.columns(3)
    col1.metric("Pairs with offspring", len(leaderboard))
    col2.metric("🟢 Improving pairs", improving)
    col3.metric("🔴 Declining pairs", declining)

    st.markdown("---")

    # Table
    rows = []
    for entry in leaderboard:
        rows.append({
            "Spawn": entry["spawn_system_id"] or "—",
            "Male": entry["male_system_id"] or "—",
            "Male Grade": entry["male_grade"] or "—",
            "Female": entry["female_system_id"] or "—",
            "Female Grade": entry["female_grade"] or "—",
            "Offspring": entry["offspring_count"],
            "Parent Avg": _fmt_score(entry["parent_avg_form"]),
            "Offspring Avg": _fmt_score(entry["offspring_avg_form"]),
            "Delta": _fmt_delta(entry["delta"]),
            "Line": entry["line_code"] or "—",
            "Gen": entry["generation"] or "—",
        })

    df = pd.DataFrame(rows)
    st.dataframe(df, use_container_width=True, hide_index=True)

    st.markdown("---")

    # Expandable detail per pair
    st.markdown("##### 🔍 Pair Details")
    for entry in leaderboard[:10]:  # top 10
        spawn_label = entry["spawn_system_id"] or "?"
        delta_str = _fmt_delta(entry["delta"])
        offspring_n = entry["offspring_count"]

        with st.expander(
            f"🧪 {spawn_label} — "
            f"{entry['male_system_id']} × {entry['female_system_id']} — "
            f"{offspring_n} offspring, delta {delta_str}"
        ):
            col1, col2 = st.columns(2)

            with col1:
                st.markdown("**♂ Male**")
                st.markdown(f"- ID: `{entry['male_system_id']}`")
                st.markdown(f"- Grade: {_grade_badge(entry['male_grade'])}", unsafe_allow_html=True)
                st.markdown(f"- Form: {_fmt_score(entry['male_form'])}")

            with col2:
                st.markdown("**♀ Female**")
                st.markdown(f"- ID: `{entry['female_system_id']}`")
                st.markdown(f"- Grade: {_grade_badge(entry['female_grade'])}", unsafe_allow_html=True)
                st.markdown(f"- Form: {_fmt_score(entry['female_form'])}")

            st.markdown("---")
            st.markdown(f"**Offspring ({offspring_n})**")
            st.markdown(f"- Avg Form: **{_fmt_score(entry['offspring_avg_form'])}**")

            # Offspring grade distribution
            dist = entry.get("offspring_grades") or {}
            if dist:
                dist_rows = []
                for g in GRADE_ORDER:
                    if g in dist:
                        dist_rows.append({"Grade": g, "Count": dist[g]})
                if dist_rows:
                    st.dataframe(dist_rows, use_container_width=True, hide_index=True)


# ============================================================
# TAB 2: GRADE INHERITANCE
# ============================================================

def _render_grade_inheritance():
    st.caption(
        "How parent grades predict offspring grade distribution. "
        "Each row shows parent grade combination → % of offspring in each grade."
    )

    result = compute_grade_inheritance_matrix()
    rows = result.get("rows", [])

    if not rows:
        _render_empty_state()
        return

    st.caption(
        f"**{result['combos_with_data']}** parent-grade combos across "
        f"**{result['total_offspring']}** offspring."
    )

    # Heatmap
    grade_order = result["grade_order"]
    matrix_data = []
    for r in rows:
        combo_label = f"{r['male_grade']} × {r['female_grade']}"
        for g in grade_order:
            matrix_data.append({
                "Parent Combo": combo_label,
                "Offspring Grade": g,
                "% of Offspring": r["dist"].get(g, 0),
                "Count": r["count"],
            })

    df = pd.DataFrame(matrix_data)

    if not df.empty:
        pivot = df.pivot(index="Parent Combo", columns="Offspring Grade", values="% of Offspring")
        # Reorder columns
        pivot = pivot.reindex(columns=[g for g in grade_order if g in pivot.columns])

        fig = px.imshow(
            pivot.values,
            x=pivot.columns.tolist(),
            y=pivot.index.tolist(),
            color_continuous_scale="Blues",
            aspect="auto",
            text_auto=".0f",
            labels=dict(color="% Offspring"),
        )
        fig.update_layout(
            height=max(300, 60 + 40 * len(pivot)),
            margin=dict(t=30, b=30, l=30, r=30),
        )
        st.plotly_chart(fig, use_container_width=True)

    st.markdown("---")

    # Table view
    st.markdown("##### 📋 Table View")
    table_rows = []
    for r in rows:
        row = {
            "Male Grade": r["male_grade"],
            "Female Grade": r["female_grade"],
            "Offspring": r["count"],
        }
        for g in grade_order:
            short = g.replace(" Grade", "")
            row[short] = f"{r['dist'].get(g, 0):.0f}%"
        table_rows.append(row)

    st.dataframe(pd.DataFrame(table_rows), use_container_width=True, hide_index=True)


# ============================================================
# TAB 3: BODY SHAPE INHERITANCE
# ============================================================

def _render_body_shape_inheritance():
    st.caption(
        "Body shape inheritance: how parent body shapes predict offspring body shapes."
    )

    result = compute_body_shape_inheritance()
    rows = result.get("rows", [])

    if not rows:
        _render_empty_state()
        return

    st.caption(f"**{result['total_offspring']}** offspring across **{len(rows)}** shape combos.")

    # Table view — clearer than heatmap for shape (which has free-text values)
    table_rows = []
    for r in rows:
        row = {
            "Male Shape": r["male_shape"],
            "Female Shape": r["female_shape"],
            "Offspring": r["count"],
        }
        for k, v in sorted(r["dist"].items()):
            row[k] = f"{v:.0f}%"
        table_rows.append(row)

    if table_rows:
        df = pd.DataFrame(table_rows).fillna("—")
        st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        st.info("No body shape data yet.")


# ============================================================
# TAB 4: FIN CHECK INHERITANCE
# ============================================================

def _render_fin_check_inheritance():
    st.caption(
        "Fin check heritability: for each fin trait, what % of offspring pass "
        "based on how many parents pass."
    )

    result = compute_fin_check_inheritance()
    checks = result.get("checks", [])

    if not checks:
        _render_empty_state()
        return

    # Summary table
    rows = []
    for c in checks:
        rows.append({
            "Fin Check": c["label"],
            "Both parents pass": (
                f"{c['both_pass']['pct']:.0f}% (n={c['both_pass']['n']})"
                if c["both_pass"]["pct"] is not None else "—"
            ),
            "One parent passes": (
                f"{c['one_pass']['pct']:.0f}% (n={c['one_pass']['n']})"
                if c["one_pass"]["pct"] is not None else "—"
            ),
            "Neither parent passes": (
                f"{c['neither_pass']['pct']:.0f}% (n={c['neither_pass']['n']})"
                if c["neither_pass"]["pct"] is not None else "—"
            ),
        })

    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    # Chart: grouped bar
    chart_rows = []
    for c in checks:
        for bucket, label in [("both", "Both pass"), ("one", "One passes"), ("neither", "Neither passes")]:
            pct = c[f"{bucket}_pass"]["pct"]
            if pct is not None:
                chart_rows.append({
                    "Fin Check": c["label"],
                    "Parent combo": label,
                    "% offspring pass": pct,
                })

    if chart_rows:
        df = pd.DataFrame(chart_rows)
        fig = px.bar(
            df,
            x="Fin Check",
            y="% offspring pass",
            color="Parent combo",
            barmode="group",
            text_auto=".0f",
        )
        fig.update_layout(
            height=420,
            margin=dict(t=30, b=80, l=30, r=30),
            xaxis_tickangle=-20,
        )
        st.plotly_chart(fig, use_container_width=True)


# ============================================================
# PAGE
# ============================================================

def render_inheritance_page():
    st.title("🧬 Inheritance Analysis")
    st.caption(
        "Which pairs produce the best fish, and which traits carry from parents to offspring. "
        "All computed from your existing data."
    )

    summary = get_inheritance_summary()

    c1, c2, c3 = st.columns(3)
    c1.metric("Spawns w/ offspring", summary["spawns_with_offspring"])
    c2.metric("Offspring analyzed", summary["total_offspring_analyzed"])
    c3.metric("Distinct pairs", summary["distinct_pairs"])

    st.caption(
        f"_Minimum {summary['min_offspring_required']} jarred offspring per spawn required for inclusion._"
    )

    st.markdown("---")

    tab1, tab2, tab3, tab4 = st.tabs([
        "🏆 Pair Leaderboard",
        "🏅 Grade Inheritance",
        "🐟 Body Shape",
        "✨ Fin Checks",
    ])

    with tab1:
        _render_pair_leaderboard()

    with tab2:
        _render_grade_inheritance()

    with tab3:
        _render_body_shape_inheritance()

    with tab4:
        _render_fin_check_inheritance()


def render_inheritance():
    """Alias entrypoint."""
    render_inheritance_page()
