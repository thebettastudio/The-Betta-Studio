# views/webrtc_test.py
# Session 26B — Minimal WebRTC test page.
# Proves the camera stream works before integrating with color analysis.
# DELETE this file after Session 26B is confirmed working.

import time
import streamlit as st
import numpy as np
from PIL import Image

try:
    from streamlit_webrtc import webrtc_streamer, VideoProcessorBase, WebRtcMode
    _WEBRTC_AVAILABLE = True
except ImportError:
    _WEBRTC_AVAILABLE = False

import av


class FrameSampler(VideoProcessorBase):
    """
    Samples frames from the WebRTC stream and stores them in memory.
    Records frame count + timestamps.
    """
    def __init__(self):
        self.last_frame = None
        self.frame_count = 0
        self.start_time = time.time()
        self.samples = []  # list of (numpy array, timestamp)

    def recv(self, frame: av.VideoFrame) -> av.VideoFrame:
        img = frame.to_ndarray(format="rgb24")
        self.last_frame = img
        self.frame_count += 1
        # Sample 1 frame per ~10 frames to save memory
        if self.frame_count % 10 == 0 and len(self.samples) < 100:
            self.samples.append((img, time.time()))
        return frame


def render_webrtc_test():
    st.title("🎥 WebRTC Camera Test")
    st.caption("Minimal page to prove camera streaming works.")

    if not _WEBRTC_AVAILABLE:
        st.error("streamlit-webrtc not installed. Run: `py -m pip install streamlit-webrtc av`")
        return

    st.markdown("### Instructions")
    st.markdown(
        "1. Click **START** below\n"
        "2. Browser will ask for camera permission — **Allow once**\n"
        "3. You should see a live camera preview\n"
        "4. Move around, verify video is smooth\n"
        "5. Click **STOP** to end the stream\n"
        "6. Frame stats appear below"
    )

    ctx = webrtc_streamer(
        key="test_stream",
        mode=WebRtcMode.SENDRECV,
        video_processor_factory=FrameSampler,
        media_stream_constraints={
            "video": {"width": {"ideal": 640}, "height": {"ideal": 480}},
            "audio": False,
        },
        async_processing=True,
    )

    # Live stats
    if ctx.video_processor:
        st.success(f"✅ Camera connected — frames received: **{ctx.video_processor.frame_count}**")

        if ctx.video_processor.last_frame is not None:
            st.markdown("**Last captured frame:**")
            st.image(ctx.video_processor.last_frame, width=320)

            # Test: run simple color detection on this frame
            from modules.color_detector import analyze_photo
            import io

            # Convert numpy RGB to JPEG bytes for the detector
            pil_img = Image.fromarray(ctx.video_processor.last_frame)
            buf = io.BytesIO()
            pil_img.save(buf, format="JPEG", quality=85)
            raw_bytes = buf.getvalue()

            with st.expander("🔬 Test: run color detector on this frame"):
                analysis = analyze_photo(raw_bytes)
                if analysis and analysis.get("ok"):
                    st.markdown(f"**Primary:** `{analysis.get('primary')}`")
                    st.markdown(f"**Secondary:** `{analysis.get('secondary')}`")
                    st.markdown(f"**Pattern:** `{analysis.get('pattern_hint')}`")
                    st.markdown(f"**Iridescence:** `{analysis.get('iridescence_level')}` (score {analysis.get('iridescence_score')})")
                    st.markdown(f"**Quality:** {analysis.get('quality', {}).get('score', 0)}/100")
                    st.markdown(f"**Palette:** {analysis.get('palette')}")
                else:
                    err = (analysis or {}).get("error", "unknown")
                    st.warning(f"Analysis failed: {err}")
    else:
        st.info("Click **START** to begin camera stream.")


def render_webrtc_test_page():
    """Alias entrypoint."""
    render_webrtc_test()


# Direct call for testing when running this file standalone:
if __name__ == "__main__":
    render_webrtc_test()
