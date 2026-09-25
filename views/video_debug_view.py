# views/video_debug_view.py
# Betta Farm Management System
# Session 26E — TEMPORARY video diagnostic page.
# Visual per-frame gate report so we can tune posture thresholds.
# Delete this file when done (also remove the nav entry in app.py).

from __future__ import annotations

import io

import numpy as np
import streamlit as st
from PIL import Image

from modules.color_detector import (
    extract_frames_from_video,
    _load_image_rgb,
    _normalize_white_balance,
    _rgb_to_hsv_numpy,
    _detect_water_tint,
    _detect_background_color_cluster,
    _mask_fish_region,
    _isolate_largest_blob,
    _compute_orientation,
    _compute_body_ratio,
    _detect_flare,
    _check_completeness,
    validate_fish_posture,
    MIN_ASPECT_RATIO,
    MIN_COVERAGE_PCT,
    MAX_SOLIDITY_FLARED,
    MIN_FLARE_PIXELS,
    MIN_TAIL_SPREAD_RATIO,
    MIN_BODY_RATIO_SIDE,
)


# ============================================================
# FRAME ANALYSIS
# ============================================================

def _analyze_one_frame(fbytes: bytes) -> dict:
    """Return full gate breakdown for one frame + JPEG preview bytes."""
    result: dict = {"preview": fbytes}

    try:
        img = _load_image_rgb(fbytes)
        if img is None:
            result["error"] = "Could not load frame"
            result["pass"] = 3
            return result
        img.thumbnail((640, 640), Image.LANCZOS)

        # Downsize preview so page loads fast
        preview = img.copy()
        preview.thumbnail((360, 360), Image.LANCZOS)
        buf = io.BytesIO()
        preview.save(buf, format="JPEG", quality=80)
        result["preview"] = buf.getvalue()

        rgb = np.asarray(img).astype(np.float32)
        rgb = _normalize_white_balance(rgb)
        rgb_u8 = np.clip(rgb, 0, 255).astype(np.uint8)
        hsv = _rgb_to_hsv_numpy(rgb_u8)

        water_tint = _detect_water_tint(hsv)
        bg_color = _detect_background_color_cluster(rgb_u8)

        mask = _mask_fish_region(hsv, rgb_u8,
                                 water_tint=water_tint, bg_color=bg_color)
        result["mask_px_raw"] = int(mask.sum())
        result["water_tint"] = water_tint is not None
        result["bg_color"] = bg_color is not None

        if mask.sum() < 50:
            result["reject"] = "No fish region found (mask < 50 px)"
            result["pass"] = 3
            return result

        blob = _isolate_largest_blob(mask, rgb_u8, min_size_pct=0.5)
        result["blob_px"] = int(blob.sum())
        result["coverage_pct"] = round(float(blob.sum() / blob.size * 100), 2)

        if blob.sum() < 50:
            result["reject"] = "Blob too small after isolation"
            result["pass"] = 3
            return result

        orientation = _compute_orientation(blob)
        flare = _detect_flare(blob, orientation)
        completeness = _check_completeness(blob, orientation)

        result["aspect"] = orientation.get("aspect", 0)
        result["body_ratio"] = round(_compute_body_ratio(blob, orientation), 2)
        result["length"] = orientation.get("length", 0)
        result["height"] = orientation.get("height", 0)
        result["angle_deg"] = orientation.get("major_axis_angle_deg", 0)
        result["head_dir"] = orientation.get("head_direction", "?")

        result["solidity"] = flare.get("solidity", 1.0)
        result["ext_px"] = flare.get("extension_px", 0)
        result["tail_ratio"] = flare.get("tail_ratio", 1.0)
        result["flared"] = flare.get("is_flared", False)
        result["flare_conf"] = flare.get("confidence", 0.0)

        result["complete"] = completeness.get("complete", False)
        result["partial_ok"] = completeness.get("partial_ok", False)
        result["completeness_reason"] = completeness.get("reason", "")

        posture = validate_fish_posture(blob, rgb_u8, result["coverage_pct"])
        result["pass"] = posture.get("pass", 3)
        result["side_label"] = posture.get("side_label", "?")
        result["posture_reason"] = posture.get("reason", "")

    except Exception as e:
        result["error"] = str(e)
        result["pass"] = 3

    return result


# ============================================================
# UI HELPERS
# ============================================================

def _pill(label: str, ok: bool, value: str = "") -> str:
    color = "#16A34A" if ok else "#DC2626"
    bg = "#DCFCE7" if ok else "#FEE2E2"
    icon = "✓" if ok else "✕"
    val = f' <span style="color:#4A5568;">({value})</span>' if value else ""
    return (
        f'<span style="display:inline-block;background:{bg};color:{color};'
        f'font-size:12px;font-weight:600;padding:3px 8px;border-radius:10px;'
        f'margin:2px 4px 2px 0;border:1px solid {color}44;">'
        f'{icon} {label}{val}</span>'
    )


def _verdict_banner(pass_num: int, reason: str = "") -> str:
    if pass_num == 1:
        bg, fg, label = "#DCFCE7", "#166534", "✅ PASS 1 — Strict"
    elif pass_num == 2:
        bg, fg, label = "#FEF3C7", "#92400E", "⚠️ PASS 2 — Regional fallback"
    else:
        bg, fg, label = "#FEE2E2", "#991B1B", "❌ REJECT — Pass 3"
    reason_html = f'<div style="font-size:12px;margin-top:4px;opacity:0.85;">{reason}</div>' if reason else ""
    return (
        f'<div style="background:{bg};color:{fg};border-radius:8px;'
        f'padding:8px 12px;font-weight:700;font-size:14px;">'
        f'{label}{reason_html}</div>'
    )


def _render_frame_card(idx: int, r: dict):
    with st.container(border=True):
        col_img, col_gates = st.columns([1, 2])

        with col_img:
            try:
                st.image(r.get("preview"), use_container_width=True)
            except Exception:
                st.caption("preview failed")
            st.caption(
                f"**Frame {idx}** · head: `{r.get('head_dir', '?')}` · "
                f"side: `{r.get('side_label', '?')}`"
            )

        with col_gates:
            if r.get("reject") or r.get("error"):
                msg = r.get("reject") or r.get("error")
                st.error(msg)
                st.markdown(_verdict_banner(3, msg), unsafe_allow_html=True)
                return

            cov = r.get("coverage_pct", 0)
            cov_ok = cov >= MIN_COVERAGE_PCT

            aspect = r.get("aspect", 0)
            side_ok = aspect >= MIN_ASPECT_RATIO

            body_ratio = r.get("body_ratio", 0.0)
            body_ok = body_ratio >= MIN_BODY_RATIO_SIDE

            flared = r.get("flared", False)
            flare_conf = r.get("flare_conf", 0.0)
            flare_ok = flared and flare_conf >= 0.5

            complete = r.get("complete", False)
            partial_ok = r.get("partial_ok", False)
            complete_ok = complete or partial_ok

            pills = (
                _pill("Coverage", cov_ok, f"{cov:.1f}% / min {MIN_COVERAGE_PCT}%")
                + _pill("Side profile", side_ok,
                        f"aspect {aspect:.2f} / min {MIN_ASPECT_RATIO}")
                + _pill("Body ratio", body_ok,
                        f"{body_ratio:.2f} / min {MIN_BODY_RATIO_SIDE}")
                + _pill("Flared", flare_ok,
                        f"conf {flare_conf:.2f} / min 0.50")
                + _pill("Completeness", complete_ok,
                        "full" if complete else ("partial OK" if partial_ok else "cut off"))
            )
            st.markdown(pills, unsafe_allow_html=True)

            st.markdown(
                f"""<div style="font-size:12px;color:#4A5568;margin-top:6px;line-height:1.6;">
                <b>Blob:</b> {r.get('blob_px', 0):,} px &nbsp;·&nbsp;
                <b>Size:</b> {r.get('length', 0):.0f}×{r.get('height', 0):.0f} px &nbsp;·&nbsp;
                <b>Angle:</b> {r.get('angle_deg', 0):.1f}°<br>
                <b>Body ratio (IBC):</b> {body_ratio:.2f} (side view needs ≥{MIN_BODY_RATIO_SIDE})<br>
                <b>Flare:</b> solidity {r.get('solidity', 1.0):.2f} (≤{MAX_SOLIDITY_FLARED}) &nbsp;·&nbsp;
                ext {r.get('ext_px', 0)} px (≥{MIN_FLARE_PIXELS}) &nbsp;·&nbsp;
                tail ratio {r.get('tail_ratio', 1.0):.2f} (≥{MIN_TAIL_SPREAD_RATIO})<br>
                <b>Completeness:</b> {r.get('completeness_reason', '—')}
                </div>""",
                unsafe_allow_html=True,
            )

            st.markdown(
                _verdict_banner(r.get("pass", 3), r.get("posture_reason", "")),
                unsafe_allow_html=True,
            )


# ============================================================
# PAGE
# ============================================================

def render_video_debug_page():
    st.header("🐛 Video Debug (temp)")
    st.caption(
        "Upload a video to see the per-frame posture gate breakdown. "
        "Delete this page when tuning is done."
    )

    col_t, col_s, col_m = st.columns(3)
    with col_t:
        sample_every = st.number_input("Sample every N frames", 1, 60, 5, 1)
    with col_s:
        max_frames = st.number_input("Max frames", 3, 60, 30, 1)
    with col_m:
        st.markdown(
            f"""<div style="font-size:12px;color:#4A5568;margin-top:28px;line-height:1.5;">
            <b>Thresholds in use:</b><br>
            aspect ≥ {MIN_ASPECT_RATIO} · coverage ≥ {MIN_COVERAGE_PCT}%<br>
            body ratio ≥ {MIN_BODY_RATIO_SIDE} (IBC side view)<br>
            solidity ≤ {MAX_SOLIDITY_FLARED} · ext ≥ {MIN_FLARE_PIXELS} px<br>
            tail ratio ≥ {MIN_TAIL_SPREAD_RATIO}
            </div>""",
            unsafe_allow_html=True,
        )

    video_file = st.file_uploader(
        "Upload video",
        type=["mp4", "mov", "webm", "m4v", "avi"],
        accept_multiple_files=False,
        key="debug_page_video_upload",
    )

    if video_file is None:
        st.info("⬆ Upload a video to begin.")
        return

    if not st.button("🔬 Run diagnostic", type="primary",
                     use_container_width=True, key="debug_page_run"):
        return

    with st.spinner("Extracting frames…"):
        try:
            frames = extract_frames_from_video(
                video_file.getvalue(),
                sample_every=int(sample_every),
                max_frames=int(max_frames),
            )
        except Exception as e:
            st.error(f"Frame extraction failed: {e}")
            return

    if not frames:
        st.error("No frames could be extracted.")
        return

    st.success(f"Extracted {len(frames)} frames.")

    results = []
    progress = st.progress(0.0, text="Analyzing frames…")
    for i, fbytes in enumerate(frames):
        results.append(_analyze_one_frame(fbytes))
        progress.progress((i + 1) / len(frames),
                          text=f"Frame {i + 1}/{len(frames)}")
    progress.empty()

    pass1 = sum(1 for r in results if r.get("pass") == 1)
    pass2 = sum(1 for r in results if r.get("pass") == 2)
    reject = sum(1 for r in results if r.get("pass") == 3)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Frames", len(results))
    c2.metric("✅ Pass 1 (strict)", pass1)
    c3.metric("⚠️ Pass 2 (regional)", pass2)
    c4.metric("❌ Reject", reject)

    if pass1 >= 3:
        st.success("Video would be accepted in STRICT mode.")
    elif pass2 >= 3:
        st.warning("Video would be accepted in REGIONAL mode (Pass 2).")
    else:
        st.error("Video would be REJECTED — not enough good frames in either pass.")

    st.markdown("---")
    st.markdown("#### Per-frame breakdown")

    cols = st.columns(2)
    for i, r in enumerate(results):
        with cols[i % 2]:
            _render_frame_card(i, r)

    with st.expander("📋 Raw JSON (developer)"):
        clean = [{k: v for k, v in r.items() if k != "preview"} for r in results]
        st.json({
            "thresholds": {
                "MIN_ASPECT_RATIO": MIN_ASPECT_RATIO,
                "MIN_COVERAGE_PCT": MIN_COVERAGE_PCT,
                "MIN_BODY_RATIO_SIDE": MIN_BODY_RATIO_SIDE,
                "MAX_SOLIDITY_FLARED": MAX_SOLIDITY_FLARED,
                "MIN_FLARE_PIXELS": MIN_FLARE_PIXELS,
                "MIN_TAIL_SPREAD_RATIO": MIN_TAIL_SPREAD_RATIO,
            },
            "results": clean,
        })
