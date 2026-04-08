import ssl; ssl._create_default_https_context = ssl._create_unverified_context
import pathlib
import sys; sys.path.append(str(pathlib.Path(__file__).parent.parent))
import streamlit as st
from common.commonmethods import *


def load_home_page():

    st.set_page_config(
        page_title="Tiger DAQE.ai Platform",
        page_icon="✨",
        layout="wide"
    )
    
    st.logo(logo_path)
    st.sidebar.title("DAQE.ai")

    # Remove Streamlit's default padding so the page feels full-bleed
    st.markdown("""
        <style>
            .block-container { padding: 0 !important; margin: 0 !important; max-width: 100% !important; }
            [data-testid="stAppViewContainer"] { padding: 0 !important; }
        </style>
    """, unsafe_allow_html=True)

    st.components.v1.html(open("datf_app/common/daqe_landing.html").read(), height=800, scrolling=True)


if __name__ == "__main__":
    create_execution_db()
    load_home_page()

