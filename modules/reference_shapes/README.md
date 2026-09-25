# Reference silhouettes for Gemini AI matching

These 4 PNG files are used by `modules/ai_frame_judge.py` to give
Gemini a visual reference for "ideal HMPK side view".

## Files

- `hmpk_traditional_show.png` — Traditional Show Plakat
  (plakat fan dorsal, pointed anal, rounded caudal 180°)
- `hmpk_symmetrical_show.png` — Symmetrical Show Plakat
  (extended dorsal, trapezoid anal, D-caudal 180°)
- `hmpk_asymmetrical_show.png` — Asymmetrical Show Plakat
  (plakat fan dorsal, pointed anal, D-caudal 180°)
- `hmpk_pet_grade.png` — Pet-grade baseline
  (relaxed/partially clamped pose for lowest tier)

## How they were generated

Run `python tools/generate_reference_shapes.py` from repo root after
dropping source images into `tools/reference_sources/`.

## How they're used

Sent to Gemini alongside candidate frames so the AI can visually
compare "ideal HMPK anatomy" vs the candidate frame, and return a
`match_score`, `posture_class`, and list of `deviations`.

Reference silhouettes are black outlines on transparent background,
800×600 PNG.
