import streamlit as st
from dashboard.components.kpi_metrics import render_kpi_metrics
from dashboard.components.realtime_logs import render_realtime_logs
from dashboard.components.feedback_view import render_feedback_view
from dashboard.analytics.user_patterns import render_user_patterns
from dashboard.analytics.ai_quality_eval import render_ai_quality_eval

st.set_page_config(page_title="SubSync Analytics Dashboard", layout="wide", page_icon="📊")

st.title("📊 SubSync 운영 및 사용자 행동 분석 대시보드")
st.markdown("YouTube 이중자막 단어 인터랙션 & Gemini Video Tutor 실시간 관제 센터")

tab1, tab2, tab3 = st.tabs(["📈 실시간 KPI & 로그", "🤖 AI Tutor 품질 분석", "🧠 사용자 학습 패턴"])

with tab1:
    render_kpi_metrics()
    st.divider()
    render_realtime_logs()

with tab2:
    render_feedback_view()
    st.divider()
    render_ai_quality_eval()

with tab3:
    render_user_patterns()
