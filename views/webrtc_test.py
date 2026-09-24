# views/webrtc_test.py
# Session 26B — Minimal WebRTC test page.
# Session 26B fix 2 — Loosened constraints, async off, better error surfacing.
# Session 26B fix 3 — Defensive getattr for error_log.

import time
import streamlit as st
import numpy as np
from PIL import Image

try:
    from streamlit_webrtc import webrtc_streamer, VideoProcessorBase, WebRtcMode
    _WEBRTC_AVAILABLE = True
except ImportError:
    _WEBRTC_AVAILABLE = False

try:
    import av
    _AV_AVAILABLE = True
except ImportError:
    _AV_AVAILABLE = False


class FrameSampler(VideoProcessorBase):
    """Samples frames from WebRTC. Stores count + last frame."""
    def __init__(self):
        self.last_frame = None
        self.frame_count = 0
        self.start_time = time.time()
        self.error_log = []

    def recv(self, frame):
        try:
            img = frame.to_ndarray(format="rgb24")
            self.last_frame = img
            self.frame_count += 1
        except Exception as e:
            self.error_log.append(f"recv error: {e}")
            print(f"recv error: {e}")
        return frame


def render_webrtc_test():
    st.title("🎥 WebRTC Camera Test")
    st.caption("Minimal page to prove camera streaming works.")

    if not _WEBRTC_AVAILABLE:
        st.error("streamlit-webrtc not installed.")
        return
    if not _AV_AVAILABLE:
        st.error("av not installed.")
        return

    st.markdown(
        "1. Click **START**\n"
        "2. Allow camera once\n"
        "3. Live preview should appear\n"
        "4. Click **🔄 Refresh stats** to see frame count"
    )

    # Loosened constraints — let browser pick resolution
    ctx = webrtc_streamer(
        key="test_stream",
        mode=WebRtcMode.SENDRECV,
        video_processor_factory=FrameSampler,
        media_stream_constraints={
            "video": True,
            "audio": False,
        },
        async_processing=False,
    )

    st.markdown("---")
    st.markdown("### 📊 Stream Status")

    # Connection state
    st.write(f"**state.playing:** `{ctx.state.playing}`")
    st.write(f"**video_processor exists:** `{ctx.video_processor is not None}`")
    st.write(f"**state.signalling:** `{ctx.state.signalling}`")

    col1, col2 = st.columns([1, 3])
    with col1:
        if st.button("🔄 Refresh stats", use_container_width=True):
            st.rerun()
    with col2:
        st.caption("Click to refresh after stream starts.")

    if ctx.video_processor:
        vp = ctx.video_processor
        st.metric("Frames received", vp.frame_count)

        # Defensive: error_log might not exist depending on streamlit-webrtc version
        error_log = getattr(vp, "error_log", None) or []
        if error_log:
            st.error("recv() errors:")
            for e in error_log[-5:]:
                st.code(e)

        # Defensive: last_frame attribute
        last_frame = getattr(vp, "last_frame", None)
        if last_frame is not None:
            st.markdown("**Last captured frame:**")
            st.image(last_frame, width=320)

            from modules.color_detector import analyze_photo
            import io
            pil_img = Image.fromarray(last_frame)
            buf = io.BytesIO()
            pil_img.save(buf, format="JPEG", quality=85)
            raw_bytes = buf.getvalue()

            with st.expander("🔬 Test: run color detector on this frame"):
                analysis = analyze_photo(raw_bytes)
                if analysis and analysis.get("ok"):
                    st.markdown(f"**Primary:** `{analysis.get('primary')}`")
                    st.markdown(f"**Secondary:** `{analysis.get('secondary')}`")
                    st.markdown(f"**Pattern:** `{analysis.get('pattern_hint')}`")
                    st.markdown(f"**Iridescence:** `{analysis.get('iridescence_level')}`")
                    st.markdown(f"**Quality:** {analysis.get('quality', {}).get('score', 0)}/100")
                    st.markdown(f"**Palette:** {analysis.get('palette')}")
                else:
                    st.warning(f"Analysis failed: {(analysis or {}).get('error', 'unknown')}")
        else:
            st.caption("No frame captured yet — click Refresh after stream is running.")
    else:
        st.caption("video_processor not created yet — click START first.")


def render_webrtc_test_page():
    render_webrtc_test()


if __name__ == "__main__":
    render_webrtc_test()
