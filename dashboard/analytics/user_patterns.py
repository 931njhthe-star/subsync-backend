import streamlit as st
from dashboard.analytics.data_loader import data_loader


def render_user_patterns():
    st.subheader("🧠 사용자 최다 클릭 & 취약 단어 Top 5")
    df = data_loader.load_click_logs()

    col1, col2 = st.columns(2)
    with col1:
        st.dataframe(df, use_container_width=True)
    with col2:
        st.bar_chart(df.set_index("word")["count"])
