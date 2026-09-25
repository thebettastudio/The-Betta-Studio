# modules/color_debug.py
# Betta Farm Management System
# Session 26E — TEMPORARY diagnostic tool.
# Not used by the production flow. Delete this file when done.
#
# Two entry points:
#   • debug_analyze_video(video_bytes) — programmatic, per-frame gate report
#   • render_video_debug_sidebar()     — Streamlit sidebar UI (upload + run)

from __future__ import annotations

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
    _detect_flare,
    _check_completeness,
    validate_fish_posture,
    _split_blob_into_regions,
    MIN_ASPECT_RATIO,
    MIN_COVERAGE_PCT,
    MAX_SOLIDITY_FLARED,
    MIN_FLARE_PIXELS,
    MIN_TAIL_SPREAD_RATIO,
)


# ============================================================
# CORE DIAGNOSTIC
# ============================================================

def debug_analyze_video(video_bytes: bytes,
                        sample_every: int = 5,
                        max_frames: int = 30) -> dict:
    """
    Per-frame gate report. Returns JSON-serializable dict.
    """
    try:
        frames = extract_frames_from_video(
            video_bytes, sample_every=sample_every, max_frames=max_frames
        )
    except Exception as e:
        return {"ok": False, "error": str(e)}

    if not frames:
        return {"ok": False, "error": "No frames extracted"}

    report = []
    for fi, fbytes in enumerate(frames):
        row = {"frame": fi}
        try:
            img = _load_image_rgb(fbytes)
            if img is None:
                row["error"] = "load failed"
                report.append(row)
                continue
            img.thumbnail((640, 640), Image.LANCZOS)

            rgb = np.asarray(img).astype(np.float32)
            rgb = _normalize_white_balance(rgb)
            rgb_u8 = np.clip(rgb, 0, 255).astype(np.uint8)
            hsv = _rgb_to_hsv_numpy(rgb_u8)

            water_tint = _detect_water_tint(hsv)
            bg_color = _detect_background_color_cluster(rgb_u8)

            mask = _mask_fish_region(hsv, rgb_u8,
                                     water_tint=water_tint, bg_color=bg_color)
            row["mask_px_raw"] = int(mask.sum())
            row["water_tint_detected"] = water_tint is not None
            row["bg_color_detected"] = bg_color is not None

            if mask.sum() < 50:
                row["reject"] = "too little fish region (mask < 50 px)"
                report.append(row)
                continue

            blob = _isolate_largest_blob(mask, rgb_u8, min_size_pct=0.5)
            row["blob_px"] = int(blob.sum())
            row["coverage_pct"] = round(float(blob.sum() / blob.size * 100), 2)

            if blob.sum() < 50:
                row["reject"] = "blob too small after isolation"
                report.append(row)
                continue

            orientation = _compute_orientation(blob)
            flare = _detect_flare(blob, orientation)
            completeness = _check_completeness(blob, orientation)

            row["aspect"] = orientation.get("aspect", 0)
            row["head_dir"] = orientation.get("head_direction", "?")
            row["length"] = orientation.get("length", 0)
            row["height"] = orientation.get("height", 0)
            row["angle_deg"] = orientation.get("major_axis_angle_deg", 0)

            row["solidity"] = flare.get("solidity", 1.0)
            row["ext_px"] = flare.get("extension_px", 0)
            row["tail_ratio"] = flare.get("tail_ratio", 1.0)
            row["flared"] = flare.get("is_flared", False)
            row["flare_conf"] = flare.get("confidence", 0.0)
            row["flare_reason"] = flare.get("reason", "")

            row["complete"] = completeness.get("complete", False)
            row["partial_ok"] = completeness.get("partial_ok", False)
            row["completeness_reason"] = completeness.get("reason", "")

            posture = validate_fish_posture(blob, rgb_u8, row["coverage_pct"])
            row["pass"] = posture.get("pass", 3)
            row["side_label"] = posture.get("side_label", "?")
            row["posture_reason"] = posture.get("reason", "")

            if row["pass"] in (1, 2):
                regions = _split_blob_into_regions(blob, orientation=orientation)
                if regions:
                    row["region_sizes"] = {
                        name: int(regions.get(f"{name}_mask",
                                              np.zeros(1, dtype=bool)).sum())
                        for name in ("head", "body", "tail", "dorsal", "anal")
                    }
        except Exception as e:
            row["error"] = str(e)
        report.append(row)

    pass1 = sum(1 for r in report if r.get("pass") == 1)
    pass2 = sum(1 for r in report if r.get("pass") == 2)
    reject = sum(1 for r in report if r.get("pass") == 3)

    return {
        "ok": True,
        "frames_total": len(frames),
        "pass1_count": pass1,
        "pass2_count": pass2,
        "reject_count": reject,
        "thresholds": {
            "MIN_ASPECT_RATIO": MIN_ASPECT_RATIO,
            "MIN_COVERAGE_PCT": MIN_COVERAGE_PCT,
            "MAX_SOLIDITY_FLARED": MAX_SOLIDITY_FLARED,
            "MIN_FLARE_PIXELS": MIN_FLARE_PIXELS,
            "MIN_TAIL_SPREAD_RATIO": MIN_TAIL_SPREAD_RATIO,
        },
        "report": report,
    }


# ============================================================
# SIDEBAR UI
# ============================================================

def render_video_debug_sidebar():
    """
    Renders inside an existing st.expander in the sidebar.
    Upload a video, click Run, get the JSON dump.
    """
    st.caption("Temp tool — diagnose why a video was rejected.")

    dbg_file = st.file_uploader(
        "Debug video",
        type=["mp4", "mov", "webm", "m4v", "avi"],
        accept_multiple_files=False,
        key="sidebar_debug_video",
        label_visibility="collapsed",
    )

    if dbg_file is None:
        st.caption("⬆ Upload a video above to run the diagnostic.")
        return

    if st.button("🐛 Run diagnostic", use_container_width=True,
                 key="sidebar_debug_run"):
        with st.spinner("Diagnosing frames..."):
            dbg = debug_analyze_video(
                dbg_file.getvalue(),
                sample_every=5,
                max_frames=30,
            )
        st.json(dbg)
