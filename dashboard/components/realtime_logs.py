import streamlit as st
import pandas as pd
from datetime import datetime


def render_realtime_logs():
    st.subheader("⚡ 실시간 사용자 행동 로그 (최근 10건)")

    sample_logs = [
        {"시간": "16:02:11", "이벤트": "word_click", "사용자": "usr_9f8c", "단어/내용": "honest", "영상 ID": "arj7oStGLkU"},
        {"시간": "16:01:45", "이벤트": "tutor_ask", "사용자": "usr_9f8c", "단어/내용": "be honest with 의미?", "영상 ID": "arj7oStGLkU"},
        {"시간": "16:01:10", "이벤트": "word_save", "사용자": "usr_33a1", "단어/내용": "living", "영상 ID": "arj7oStGLkU"},
        {"시간": "16:00:22", "이벤트": "feedback", "사용자": "usr_9f8c", "단어/내용": "👍 도움됨", "영상 ID": "arj7oStGLkU"},
    ]

    df = pd.DataFrame(sample_logs)
    st.dataframe(df, use_container_width=True)
