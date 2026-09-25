# views/video_debug_view.py
# Betta Farm Management System
# Session 26H.6 — Fish-shaped blob filter (reject tall-thin divider blobs).
# Delete this file when done (also remove the nav entry in app.py).

from __future__ import annotations

import io
from typing import Optional

import numpy as np
import streamlit as st
from PIL import Image, ImageDraw

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
    _per_frame_motion_blobs,
    _track_largest_blob,
    _build_trajectory_mask,
    _head_direction_from_track,
    compute_ibc_score,
    POSTURE_CLASS_RANK,
    MIN_ASPECT_RATIO,
    MIN_COVERAGE_PCT,
    MAX_SOLIDITY_FLARED,
    MIN_FLARE_PIXELS,
    MIN_TAIL_SPREAD_RATIO,
    MIN_BODY_RATIO_SIDE,
)


# ============================================================
# OVERLAY RENDERERS
# ============================================================

def _render_blob_overlay(img_pil: Image.Image, blob_mask: np.ndarray) -> bytes:
    try:
        base = np.asarray(img_pil.convert("RGB")).copy()
        base[blob_mask] = (
            base[blob_mask] * 0.4 + np.array([255, 0, 0]) * 0.6
        ).astype(np.uint8)
        out = Image.fromarray(base)
        out.thumbnail((360, 360), Image.LANCZOS)
        buf = io.BytesIO()
        out.save(buf, format="JPEG", quality=80)
        return buf.getvalue()
    except Exception:
        return None


def _compute_classical_bbox(fbytes: bytes) -> Optional[dict]:
    """
    Compute a bbox around the fish using classical HSV mask + smart blob
    selection. Filters out tall thin regions (tank dividers).
    Returns {"x", "y", "w", "h"} normalized 0..1, or None.
    """
    try:
        img = _load_image_rgb(fbytes)
        if img is None:
            return None
        img.thumbnail((640, 640), Image.LANCZOS)
        W, H = img.size

        rgb = np.asarray(img).astype(np.float32)
        rgb = _normalize_white_balance(rgb)
        rgb_u8 = np.clip(rgb, 0, 255).astype(np.uint8)
        hsv = _rgb_to_hsv_numpy(rgb_u8)

        water_tint = _detect_water_tint(hsv)
        bg_color = _detect_background_color_cluster(rgb_u8)

        mask = _mask_fish_region(hsv, rgb_u8,
                                 water_tint=water_tint, bg_color=bg_color)
        if mask.sum() < 50:
            return None

        # Enumerate ALL blobs, pick the best fish-shaped one
        try:
            from scipy import ndimage as _nd
            labeled, num = _nd.label(mask)
        except ImportError:
            labeled, num = None, 0

        if num == 0:
            # Fallback: use whole mask
            ys, xs = np.where(mask)
        else:
            best_blob = None
            best_score = -1.0

            for comp_id in range(1, num + 1):
                blob = (labeled == comp_id)
                area = int(blob.sum())
                if area < 100:
                    continue

                ys_b, xs_b = np.where(blob)
                bw = int(xs_b.max() - xs_b.min() + 1)
                bh = int(ys_b.max() - ys_b.min() + 1)

                # Reject tall-thin regions (tank dividers)
                if bh > bw * 1.2:
                    continue
                if bw < 30 or bh < 20:
                    continue

                aspect = max(bw, bh) / max(1, min(bw, bh))
                if aspect > 2.5:
                    continue

                # Prefer blob nearest to frame center
                cx_blob = (xs_b.min() + xs_b.max()) / 2.0
                cy_blob = (ys_b.min() + ys_b.max()) / 2.0
                cx_frame, cy_frame = W / 2.0, H / 2.0
                dist = ((cx_blob - cx_frame) ** 2 + (cy_blob - cy_frame) ** 2) ** 0.5
                center_bonus = 1.0 - min(1.0, dist / (max(W, H) * 0.5))

                score = area * 0.001 + center_bonus * 2.0

                if score > best_score:
                    best_score = score
                    best_blob = blob

            if best_blob is None:
                # No fish-shaped blob found — fall back to whole mask
                ys, xs = np.where(mask)
            else:
                ys, xs = np.where(best_blob)

        if len(xs) == 0:
            return None

        x0, x1 = int(xs.min()), int(xs.max())
        y0, y1 = int(ys.min()), int(ys.max())

        # Pad 5%
        pad_x = int((x1 - x0) * 0.05)
        pad_y = int((y1 - y0) * 0.05)
        x0 = max(0, x0 - pad_x)
        y0 = max(0, y0 - pad_y)
        x1 = min(W, x1 + pad_x)
        y1 = min(H, y1 + pad_y)

        return {
            "x": x0 / W,
            "y": y0 / H,
            "w": (x1 - x0) / W,
            "h": (y1 - y0) / H,
        }
    except Exception:
        return None


def _render_bbox_overlay(img_pil: Image.Image, bbox: dict,
                          size: int = 360, width: int = 4) -> Optional[bytes]:
    try:
        if not bbox:
            return None
        out = img_pil.copy().convert("RGB")
        W, H = out.size
        x = int(bbox["x"] * W)
        y = int(bbox["y"] * H)
        w = int(bbox["w"] * W)
        h = int(bbox["h"] * H)
        draw = ImageDraw.Draw(out)
        draw.rectangle([x, y, x + w, y + h], outline=(0, 220, 0), width=width)
        out.thumbnail((size, size), Image.LANCZOS)
        buf = io.BytesIO()
        out.save(buf, format="JPEG", quality=85)
        return buf.getvalue()
    except Exception:
        return None


def _render_trajectory_overlay(img_pil: Image.Image,
                                 traj_mask: np.ndarray) -> bytes:
    try:
        base = np.asarray(img_pil.convert("RGB")).copy()
        if traj_mask.shape == base.shape[:2]:
            base[traj_mask] = (
                base[traj_mask] * 0.5 + np.array([0, 200, 100]) * 0.5
            ).astype(np.uint8)
        out = Image.fromarray(base)
        out.thumbnail((360, 360), Image.LANCZOS)
        buf = io.BytesIO()
        out.save(buf, format="JPEG", quality=80)
        return buf.getvalue()
    except Exception:
        return None


def _render_trajectory_map(frames_shape: tuple[int, int], track: list) -> bytes:
    try:
        H, W = frames_shape
        canvas = Image.new("RGB", (W, H), (240, 244, 248))
        draw = ImageDraw.Draw(canvas)

        for t, b in enumerate(track):
            if b is None:
                continue
            x0, y0, x1, y1 = b["bbox"]
            draw.rectangle([x0, y0, x1, y1], outline=(200, 200, 200), width=1)

        points = [(b["centroid"]) for b in track if b is not None]
        for i in range(1, len(points)):
            draw.line([points[i - 1], points[i]], fill=(220, 40, 40), width=2)

        for t, b in enumerate(track):
            if b is None:
                continue
            cx, cy = b["centroid"]
            r = 4
            draw.ellipse([cx - r, cy - r, cx + r, cy + r],
                         fill=(255, 100, 0), outline=(150, 0, 0))
            if t % 3 == 0:
                draw.text((cx + 6, cy - 6), str(t), fill=(0, 0, 0))

        canvas.thumbnail((480, 480), Image.LANCZOS)
        buf = io.BytesIO()
        canvas.save(buf, format="JPEG", quality=85)
        return buf.getvalue()
    except Exception:
        return None


# ============================================================
# FRAME ANALYSIS
# ============================================================

def _analyze_one_frame(fbytes: bytes, traj_mask=None, head_override=None,
                         pass_override=None, real_fish_bbox=None) -> dict:
    result: dict = {"preview": fbytes}

    try:
        img = _load_image_rgb(fbytes)
        if img is None:
            result["error"] = "Could not load frame"
            result["pass"] = 3
            return result
        img.thumbnail((640, 640), Image.LANCZOS)

        preview = img.copy()
        preview.thumbnail((360, 360), Image.LANCZOS)
        buf = io.BytesIO()
        preview.save(buf, format="JPEG", quality=80)
        result["preview"] = buf.getvalue()

        if real_fish_bbox:
            bo = _render_bbox_overlay(img, real_fish_bbox)
            if bo:
                result["bbox_overlay"] = bo

        if traj_mask is not None:
            to = _render_trajectory_overlay(img, traj_mask)
            if to:
                result["traj_overlay"] = to

        rgb = np.asarray(img).astype(np.float32)
        rgb = _normalize_white_balance(rgb)
        rgb_u8 = np.clip(rgb, 0, 255).astype(np.uint8)
        hsv = _rgb_to_hsv_numpy(rgb_u8)

        water_tint = _detect_water_tint(hsv)
        bg_color = _detect_background_color_cluster(rgb_u8)

        mask = _mask_fish_region(hsv, rgb_u8,
                                 water_tint=water_tint, bg_color=bg_color)

        if real_fish_bbox:
            try:
                from modules.ai_frame_judge import bbox_to_mask
                bb = bbox_to_mask(mask.shape, real_fish_bbox)
                if bb is not None:
                    mask &= bb
            except Exception:
                pass

        if traj_mask is not None and traj_mask.shape == mask.shape:
            mask &= traj_mask

        result["mask_px_raw"] = int(mask.sum())
        result["water_tint"] = water_tint is not None
        result["bg_color"] = bg_color is not None
        result["bbox_applied"] = real_fish_bbox is not None

        if mask.sum() < 50:
            result["reject"] = "No fish region found (mask < 50 px)"
            result["pass"] = 3
            return result

        blob = _isolate_largest_blob(mask, rgb_u8, min_size_pct=0.5)
        result["blob_px"] = int(blob.sum())
        result["coverage_pct"] = round(float(blob.sum() / blob.size * 100), 2)

        overlay_bytes = _render_blob_overlay(img, blob)
        if overlay_bytes:
            result["overlay"] = overlay_bytes

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
        result["head_dir"] = head_override or orientation.get("head_direction", "?")

        result["solidity"] = flare.get("solidity", 1.0)
        result["ext_px"] = flare.get("extension_px", 0)
        result["tail_ratio"] = flare.get("tail_ratio", 1.0)
        result["flared"] = flare.get("is_flared", False)
        result["flare_conf"] = flare.get("confidence", 0.0)

        result["complete"] = completeness.get("complete", False)
        result["partial_ok"] = completeness.get("partial_ok", False)
        result["completeness_reason"] = completeness.get("reason", "")

        posture = validate_fish_posture(blob, rgb_u8, result["coverage_pct"])
        if pass_override is not None and pass_override in (1, 2):
            result["pass"] = pass_override
            result["posture_reason"] = "AI-approved frame (Gemini)"
        else:
            result["pass"] = posture.get("pass", 3)
            result["posture_reason"] = posture.get("reason", "")

        result["side_label"] = posture.get("side_label", "?")
        if head_override == "left":
            result["side_label"] = "A"
        elif head_override == "right":
            result["side_label"] = "B"

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


def _posture_color(posture_class: str) -> tuple:
    mapping = {
        "fully_flared":     ("#DCFCE7", "#166534"),
        "mostly_flared":    ("#ECFCCB", "#3F6212"),
        "partially_flared": ("#FEF3C7", "#92400E"),
        "clamped":          ("#FEE2E2", "#991B1B"),
        "unusable":         ("#E5E7EB", "#374151"),
    }
    return mapping.get(posture_class, ("#E5E7EB", "#374151"))


# ============================================================
# AI GALLERY
# ============================================================

def _render_ai_gallery(frames: list, ai_verdicts: list, ai_rank: dict):
    if not ai_verdicts:
        return

    approved = [v for v in ai_verdicts
                if v.get("posture_class", "unusable") != "unusable"]

    if not approved:
        st.error("No frames were approved by Gemini.")
        return

    approved.sort(key=lambda v: ai_rank.get(v["frame_index"], 9999))

    st.markdown("### 🖼️ AI-approved frames")
    st.caption(
        f"Gemini found **{len(approved)} frames** with a usable side view. "
        f"Green box = fish-shaped classical detection (independent of AI)."
    )

    cols_per_row = 4
    for row_start in range(0, len(approved), cols_per_row):
        row = approved[row_start:row_start + cols_per_row]
        cols = st.columns(cols_per_row)
        for i, v in enumerate(row):
            fi = v["frame_index"]
            with cols[i]:
                _render_gallery_card(frames, fi, v, ai_rank.get(fi))


def _render_gallery_card(frames: list, frame_idx: int,
                          verdict: dict, rank: int = None):
    posture_class = verdict.get("posture_class", "unusable")
    pc_bg, pc_fg = _posture_color(posture_class)
    match_score = verdict.get("match_score", 0.0)
    flare_score = verdict.get("flare_score", 0.0)
    confidence = verdict.get("confidence", 0.0)
    head_dir = verdict.get("head_direction", "?")
    matched_ref = verdict.get("matched_reference", "none")
    reason = verdict.get("reason", "")
    deviations = verdict.get("deviations", []) or []

    # ALWAYS use classical fish-shaped bbox
    thumb_bytes = None
    if 0 <= frame_idx < len(frames):
        try:
            img = _load_image_rgb(frames[frame_idx])
            if img is not None:
                bbox = _compute_classical_bbox(frames[frame_idx])

                if isinstance(bbox, dict):
                    thumb_bytes = _render_bbox_overlay(img, bbox,
                                                        size=280, width=4)
                else:
                    img.thumbnail((280, 280), Image.LANCZOS)
                    buf = io.BytesIO()
                    img.save(buf, format="JPEG", quality=85)
                    thumb_bytes = buf.getvalue()
        except Exception:
            thumb_bytes = None

    with st.container(border=True):
        rank_txt = f"#{rank} · " if rank is not None else ""
        st.markdown(f"**{rank_txt}Frame {frame_idx}**")

        if thumb_bytes:
            try:
                st.image(thumb_bytes, use_container_width=True)
            except Exception:
                st.caption("(preview failed)")
        else:
            st.caption("(no preview)")

        st.markdown(
            f'<div style="background:{pc_bg};color:{pc_fg};border-radius:6px;'
            f'padding:4px 8px;font-size:12px;font-weight:600;text-align:center;'
            f'margin:6px 0;">'
            f'{posture_class.replace("_", " ").title()}'
            f'</div>',
            unsafe_allow_html=True,
        )

        st.caption(
            f"match **{match_score:.2f}** · flare **{flare_score:.2f}** · "
            f"conf **{confidence:.2f}**"
        )
        st.caption(f"head: `{head_dir}` · ref: `{matched_ref}`")

        if reason:
            st.markdown(
                f'<div style="font-size:11px;color:#4A5568;'
                f'font-style:italic;">{reason}</div>',
                unsafe_allow_html=True,
            )

        if deviations:
            with st.expander(f"Deviations ({len(deviations)})", expanded=False):
                for dev in deviations:
                    st.markdown(f"- {dev}")


# ============================================================
# FRAME CARD
# ============================================================

def _render_frame_card(idx: int, r: dict, ai_verdict: dict = None,
                         rank: int = None):
    with st.container(border=True):
        col_img, col_gates = st.columns([1, 2])

        with col_img:
            tab_labels = ["Original"]
            tab_contents = []

            if r.get("bbox_overlay"):
                tab_labels.append("AI bbox")
                tab_contents.append(r.get("bbox_overlay"))
            if r.get("overlay"):
                tab_labels.append("Blob mask")
                tab_contents.append(r.get("overlay"))
            if r.get("traj_overlay"):
                tab_labels.append("Trajectory")
                tab_contents.append(r.get("traj_overlay"))

            tabs = st.tabs(tab_labels)

            with tabs[0]:
                try:
                    st.image(r.get("preview"), use_container_width=True)
                except Exception:
                    st.caption("preview failed")

            for i, content in enumerate(tab_contents, start=1):
                with tabs[i]:
                    try:
                        st.image(content, use_container_width=True)
                    except Exception:
                        st.caption("overlay failed")

            caption = (
                f"**Frame {idx}** · head: `{r.get('head_dir', '?')}` · "
                f"side: `{r.get('side_label', '?')}`"
            )
            if rank is not None:
                caption = f"**#{rank}** · " + caption
            st.caption(caption)

        with col_gates:
            if ai_verdict is not None:
                posture_class = ai_verdict.get("posture_class", "unusable")
                pc_bg, pc_fg = _posture_color(posture_class)
                match_score = ai_verdict.get("match_score", 0.0)
                flare_score = ai_verdict.get("flare_score", 0.0)
                matched_ref = ai_verdict.get("matched_reference", "none")
                confidence = ai_verdict.get("confidence", 0.0)
                reason = ai_verdict.get("reason", "")

                st.markdown(
                    f'<div style="background:{pc_bg};color:{pc_fg};'
                    f'border-radius:6px;padding:8px 12px;font-size:13px;'
                    f'font-weight:600;margin-bottom:6px;">'
                    f'🤖 <b>{posture_class.replace("_", " ").title()}</b> · '
                    f'match <b>{match_score:.2f}</b> · '
                    f'flare <b>{flare_score:.2f}</b> · '
                    f'ref <code>{matched_ref}</code> · '
                    f'conf <b>{confidence:.2f}</b>'
                    f'<div style="font-weight:400;margin-top:4px;">{reason}</div>'
                    f'</div>',
                    unsafe_allow_html=True,
                )

                deviations = ai_verdict.get("deviations", []) or []
                if deviations:
                    with st.expander(f"Deviations ({len(deviations)})", expanded=False):
                        for dev in deviations:
                            st.markdown(f"- {dev}")

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
            if r.get("bbox_applied"):
                pills += _pill("AI bbox applied", True, "")

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
# REFERENCE PANEL
# ============================================================

def _render_references_panel():
    try:
        from modules.reference_shapes import (
            load_reference_images, has_all_references, missing_references,
        )
    except Exception:
        st.caption("Reference module unavailable.")
        return

    if not has_all_references():
        st.warning(
            f"⚠️ Some reference silhouettes are missing: "
            f"`{', '.join(missing_references())}`."
        )
        return

    with st.expander("🎯 Reference silhouettes used for matching", expanded=False):
        refs = load_reference_images()
        cols = st.columns(len(refs))
        for i, ref in enumerate(refs):
            with cols[i]:
                st.caption(f"`{ref['name']}`")
                try:
                    img = Image.open(io.BytesIO(ref["bytes"]))
                    st.image(img, use_container_width=True)
                except Exception:
                    st.caption("(cannot preview)")


# ============================================================
# PAGE
# ============================================================

def render_video_debug_page():
    st.header("🐛 Video Debug (temp)")
    st.caption(
        "Upload a video to see the per-frame posture gates + Gemini AI "
        "matching against HMPK reference silhouettes."
    )

    col_t, col_s, col_m = st.columns(3)
    with col_t:
        sample_every = st.number_input("Sample every N frames", 1, 60, 5, 1)
    with col_s:
        max_frames = st.number_input("Max frames", 3, 60, 30, 1)
    with col_m:
        st.markdown(
            f"""<div style="font-size:12px;color:#4A5568;margin-top:28px;line-height:1.5;">
            <b>Thresholds:</b><br>
            aspect ≥ {MIN_ASPECT_RATIO} · coverage ≥ {MIN_COVERAGE_PCT}%<br>
            body ratio ≥ {MIN_BODY_RATIO_SIDE} · solidity ≤ {MAX_SOLIDITY_FLARED}<br>
            ext ≥ {MIN_FLARE_PIXELS} px · tail ratio ≥ {MIN_TAIL_SPREAD_RATIO}
            </div>""",
            unsafe_allow_html=True,
        )

    ai_available = False
    try:
        from modules.ai_frame_judge import is_ai_available
        ai_available = is_ai_available()
    except Exception:
        ai_available = False

    if ai_available:
        st.success("🤖 **Gemini AI judge is active.** Frames sent to Gemini with reference silhouettes.")
        _render_references_panel()
    else:
        st.warning(
            "⚠️ **Gemini AI not configured.** Add `GOOGLE_API_KEY` to Streamlit "
            "secrets. Falling back to classical pipeline."
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

    with st.spinner("Decoding frames…"):
        frames_rgb = []
        for fbytes in frames:
            img = _load_image_rgb(fbytes)
            if img is None:
                frames_rgb.append(np.zeros((640, 640, 3), dtype=np.uint8))
                continue
            img.thumbnail((640, 640), Image.LANCZOS)
            frames_rgb.append(np.asarray(img.convert("RGB")).astype(np.uint8))

    ai_verdicts = None
    ai_best = None
    ai_map = {}
    ai_rank = {}

    if ai_available:
        with st.spinner("🤖 Asking Gemini to match frames against HMPK references… may take 20–40s"):
            try:
                from modules.ai_frame_judge import judge_frames
                ai_result = judge_frames(
                    frames_bytes=frames,
                    frame_indices=list(range(len(frames))),
                )
                if isinstance(ai_result, dict):
                    ai_verdicts = ai_result.get("frames", [])
                    ai_best = ai_result.get("best", None)
                elif isinstance(ai_result, list):
                    ai_verdicts = ai_result
                    ai_best = None
            except Exception as e:
                st.error(f"Gemini judge failed: {e}")
                ai_verdicts = None

    if ai_verdicts:
        ranked = sorted(
            ai_verdicts,
            key=lambda v: (
                -POSTURE_CLASS_RANK.get(v.get("posture_class", "unusable"), 1),
                -v.get("flare_score", 0.0),
                -v.get("match_score", 0.0),
            ),
        )
        ai_map = {v["frame_index"]: v for v in ai_verdicts}
        for i, v in enumerate(ranked):
            ai_rank[v["frame_index"]] = i + 1

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Total frames", len(ai_verdicts))
        c2.metric("✅ Fully flared", sum(1 for v in ai_verdicts
                                          if v.get("posture_class") == "fully_flared"))
        c3.metric("👍 Mostly flared", sum(1 for v in ai_verdicts
                                            if v.get("posture_class") == "mostly_flared"))
        c4.metric("❌ Unusable", sum(1 for v in ai_verdicts
                                       if v.get("posture_class") == "unusable"))

        top_posture = ranked[0].get("posture_class", "unusable") if ranked else "unusable"
        if top_posture == "unusable":
            st.error("No usable frames found — video rejected.")
        else:
            st.success(
                f"**Best available posture:** `{top_posture.replace('_', ' ')}` "
                f"(flare {ranked[0].get('flare_score', 0):.2f}, "
                f"match {ranked[0].get('match_score', 0):.2f})"
            )

        if ai_best:
            with st.expander("🏆 Gemini's best frame + suggested crop", expanded=True):
                bidx = ai_best.get("frame_index", -1)
                if 0 <= bidx < len(frames):
                    col_orig, col_crop = st.columns(2)
                    with col_orig:
                        st.caption(f"**Original — frame {bidx}**")
                        try:
                            oi = _load_image_rgb(frames[bidx])
                            if oi is not None:
                                st.image(oi, use_container_width=True)
                        except Exception:
                            pass
                    with col_crop:
                        st.caption("**Suggested crop (profile photo)**")
                        try:
                            from modules.ai_frame_judge import crop_frame_to_bbox
                            cb = crop_frame_to_bbox(frames, ai_best)
                            if cb:
                                st.image(cb, use_container_width=True)
                        except Exception as e:
                            st.caption(f"Crop failed: {e}")
                    st.caption(f"_{ai_best.get('reason', '')}_")

        _render_ai_gallery(frames, ai_verdicts, ai_rank)

        with st.expander(f"🤖 All {len(ai_verdicts)} AI verdicts (compact)", expanded=False):
            for v in ranked:
                pc = v.get("posture_class", "unusable")
                pc_bg, pc_fg = _posture_color(pc)
                st.markdown(
                    f'<div style="background:{pc_bg};color:{pc_fg};'
                    f'border-radius:6px;padding:6px 10px;font-size:13px;'
                    f'margin:4px 0;">'
                    f'<b>#{ai_rank[v["frame_index"]]}</b> · frame {v["frame_index"]} · '
                    f'<b>{pc.replace("_", " ")}</b> · '
                    f'match {v.get("match_score", 0):.2f} · '
                    f'flare {v.get("flare_score", 0):.2f} · '
                    f'head {v.get("head_direction", "?")} · '
                    f'ref {v.get("matched_reference", "none")} · '
                    f'conf {v.get("confidence", 0):.2f}'
                    f'</div>',
                    unsafe_allow_html=True,
                )

    with st.spinner("Classical tracking (comparison)…"):
        blobs_per_frame = _per_frame_motion_blobs(frames_rgb)
        track = _track_largest_blob(blobs_per_frame)

    tracked_n = sum(1 for b in track if b is not None)
    coverage_pct = tracked_n / max(1, len(frames)) * 100

    st.info(
        f"Classical tracking: **{tracked_n}/{len(frames)} frames** "
        f"({coverage_pct:.0f}%) with confirmed fish location."
    )

    with st.expander("🗺️ Fish trajectory map (classical)", expanded=False):
        tm = _render_trajectory_map(frames_rgb[0].shape[:2], track)
        if tm:
            st.image(tm, caption="Tracked fish path")
        else:
            st.caption("No trajectory")

    if ai_verdicts:
        ordered_indices = [v["frame_index"] for v in sorted(
            ai_verdicts,
            key=lambda v: ai_rank.get(v["frame_index"], 9999),
        )]
        for i in range(len(frames)):
            if i not in ordered_indices:
                ordered_indices.append(i)
    else:
        ordered_indices = list(range(len(frames)))

    results = []
    progress = st.progress(0.0, text="Analyzing frames…")
    for step, i in enumerate(ordered_indices):
        ai_v = ai_map.get(i) if ai_map else None

        head_override = None
        pass_override = None
        bbox = None

        if ai_v is not None:
            hd = ai_v.get("head_direction")
            if hd in ("left", "right", "up", "down"):
                head_override = hd
            if ai_v.get("posture_class") != "unusable":
                pass_override = 1
            # Gemini's bbox intentionally ignored (unreliable)

        if head_override is None and track[i] is not None:
            tmp_orient = {"major_axis_angle_deg": 0, "head_direction": "unknown"}
            h = _head_direction_from_track(track, i, tmp_orient)
            if h != "unknown":
                head_override = h

        traj_mask = _build_trajectory_mask(frames_rgb[i].shape[:2], track, i)

        r = _analyze_one_frame(
            frames[i],
            traj_mask=traj_mask,
            head_override=head_override,
            pass_override=pass_override,
            real_fish_bbox=bbox,
        )
        r["_frame_index"] = i
        results.append(r)
        progress.progress((step + 1) / len(ordered_indices),
                          text=f"Frame {step + 1}/{len(ordered_indices)}")
    progress.empty()

    pass1 = sum(1 for r in results if r.get("pass") == 1)
    pass2 = sum(1 for r in results if r.get("pass") == 2)
    reject = sum(1 for r in results if r.get("pass") == 3)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Frames", len(results))
    c2.metric("✅ Pass 1", pass1)
    c3.metric("⚠️ Pass 2", pass2)
    c4.metric("❌ Reject", reject)

    if pass1 >= 1:
        st.success("Video would be accepted in STRICT mode.")
    elif pass2 >= 1:
        st.warning("Video would be accepted in REGIONAL mode.")
    else:
        st.error("Video would be REJECTED.")

    if ai_verdicts:
        top_verdict = sorted(
            ai_verdicts,
            key=lambda v: ai_rank.get(v["frame_index"], 9999),
        )[0]

        dummy_consensus = {"body_length_depth_ratio": None}
        ibc = compute_ibc_score(top_verdict, dummy_consensus)

        st.markdown("---")
        st.markdown("#### 🏆 IBC Form Grade (preliminary)")
        ic1, ic2, ic3 = st.columns(3)
        ic1.metric("Score", ibc.get("score", "—"))
        ic2.metric("Grade", ibc.get("grade", "—"))
        ic3.metric("Deviations", len(ibc.get("deviations", [])))

        faults = ibc.get("faults_applied", [])
        if faults:
            with st.expander(f"Faults applied ({len(faults)})", expanded=False):
                for f in faults:
                    st.markdown(
                        f"- **{f['level'].title()}** (−{f['points']}) — "
                        f"{f['reason']}  \n"
                        f"  _source: {f['source']}_"
                    )

    st.markdown("---")
    st.markdown("#### Per-frame breakdown (AI-ranked)")

    cols = st.columns(2)
    for i, r in enumerate(results):
        fi = r.get("_frame_index", i)
        with cols[i % 2]:
            _render_frame_card(
                fi, r,
                ai_verdict=ai_map.get(fi),
                rank=ai_rank.get(fi) if ai_map else None,
            )

    with st.expander("📋 Raw JSON (developer)"):
        clean = [{
            k: v for k, v in r.items()
            if k not in ("preview", "overlay", "bbox_overlay", "traj_overlay")
        } for r in results]
        st.json({
            "thresholds": {
                "MIN_ASPECT_RATIO": MIN_ASPECT_RATIO,
                "MIN_COVERAGE_PCT": MIN_COVERAGE_PCT,
                "MIN_BODY_RATIO_SIDE": MIN_BODY_RATIO_SIDE,
                "MAX_SOLIDITY_FLARED": MAX_SOLIDITY_FLARED,
                "MIN_FLARE_PIXELS": MIN_FLARE_PIXELS,
                "MIN_TAIL_SPREAD_RATIO": MIN_TAIL_SPREAD_RATIO,
            },
            "ai_verdicts": ai_verdicts,
            "ai_best": ai_best,
            "results": clean,
        })
