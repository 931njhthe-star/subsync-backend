import streamlit as st
import pandas as pd


def render_feedback_view():
    st.subheader("🤖 Video Tutor 답변 만족도 및 부정 피드백 사유")
    col1, col2 = st.columns([1, 2])

    with col1:
        st.metric("긍정 피드백 (👍)", "322 건")
        st.metric("부정 피드백 (👎)", "20 건")

    with col2:
        reasons = pd.DataFrame({
            "사유": ["설명이 너무 길어요", "설명이 어려워요", "영상과 무관해요", "오답/틀린 설명"],
            "건수": [10, 6, 3, 1]
        })
        st.bar_chart(reasons.set_index("사유"))
