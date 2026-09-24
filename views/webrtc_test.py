# views/webrtc_test.py
# Session 26B — Minimal WebRTC test page.
# Session 26B fix — Poll ctx.state for live stats + manual refresh.

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
    """
    Samples frames from the WebRTC stream.
    Stores frame count, last frame, and up to 100 sampled frames.
    """
    def __init__(self):
        self.last_frame = None
        self.frame_count = 0
        self.start_time = time.time()
        self.samples = []

    def recv(self, frame):
        try:
            img = frame.to_ndarray(format="rgb24")
            self.last_frame = img
            self.frame_count += 1
            if self.frame_count % 10 == 0 and len(self.samples) < 100:
                self.samples.append((img, time.time()))
        except Exception as e:
            print(f"recv error: {e}")
        return frame


def render_webrtc_test():
    st.title("🎥 WebRTC Camera Test")
    st.caption("Minimal page to prove camera streaming works.")

    if not _WEBRTC_AVAILABLE:
        st.error("streamlit-webrtc not installed. Run: `py -m pip install streamlit-webrtc av`")
        return

    if not _AV_AVAILABLE:
        st.error("av (PyAV) not installed. Run: `py -m pip install av`")
        return

    st.markdown("### Instructions")
    st.markdown(
        "1. Click **START** below\n"
        "2. Browser will ask for camera permission — **Allow once**\n"
        "3. You should see a live camera preview\n"
        "4. Click **🔄 Refresh stats** to see the frame count\n"
        "5. Click **STOP** to end the stream"
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

    st.markdown("---")
    st.markdown("### 📊 Stream Status")

    # Connection state (always fresh)
    if ctx.state.playing:
        st.success("✅ Stream is PLAYING")
    else:
        st.info("⏸ Stream is stopped — click START above")

    # Manual refresh button
    col1, col2 = st.columns([1, 3])
    with col1:
        if st.button("🔄 Refresh stats", use_container_width=True):
            st.rerun()
    with col2:
        st.caption("Frame count updates only when you click Refresh (Streamlit limitation).")

    # Frame stats from the video processor
    if ctx.video_processor:
        vp = ctx.video_processor
        st.metric("Frames received", vp.frame_count)

        if vp.last_frame is not None:
            st.markdown("**Last captured frame:**")
            st.image(vp.last_frame, width=320)

            # Run color detector on the last frame
            from modules.color_detector import analyze_photo
            import io

            pil_img = Image.fromarray(vp.last_frame)
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
            st.caption("No frame captured yet — the callback may not have run.")
    else:
        st.caption("Waiting for stream to start...")


def render_webrtc_test_page():
    """Alias entrypoint."""
    render_webrtc_test()


if __name__ == "__main__":
    render_webrtc_test()
