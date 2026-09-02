import streamlit as st


def render_kpi_metrics():
    st.subheader("📌 핵심 운영 지표 (KPI)")
    col1, col2, col3, col4 = st.columns(4)

    col1.metric("일일 활성 사용자 (DAU)", "128 명", "+12%")
    col2.metric("총 단어 클릭 수", "1,420 회", "+24%")
    col3.metric("Video Tutor 질의 수", "342 회", "+8%")
    col4.metric("AI 답변 만족도", "94.2 %", "+1.5%p")
