import streamlit as st
import pandas as pd


def render_ai_quality_eval():
    st.subheader("⚡ AI 응답 속도 및 답변 길이와 만족도 상관관계")

    perf_df = pd.DataFrame({
        "응답 속도 (ms)": [350, 420, 580, 890, 1200],
        "답변 만족도 (%)": [98, 96, 94, 82, 70]
    })

    st.line_chart(perf_df.set_index("응답 속도 (ms)"))
    st.caption("💡 분석 결과: 응답 시간이 600ms를 초과할 때 사용자 만족도가 급격히 하락하는 경향을 보입니다.")
