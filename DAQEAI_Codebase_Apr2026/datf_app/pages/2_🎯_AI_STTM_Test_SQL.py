import streamlit as st
from datf_app.common.commonmethods import *

input_template_folders = ["Template_A", "Template_B"]

def sql_sttm_generation():

    st.set_page_config(
        page_title="AI powered Test SQL Generator"
    )
    st.logo(logo_path)
    st.title("AI Test Design SQL Generation")

    template_type = st.radio(
            "Choose your mapping template type:", input_template_folders,
            horizontal=True, index=0)
    template_type = template_type.lower()

    with st.expander("Upload STTM Config Excel file here", expanded=False):
        sttm_file = st.file_uploader("STTM Config Excel file",
                                    type='xlsx', accept_multiple_files=False)
        convention = 'sttm_'
        upload_status = file_upload_all(sttm_file, f'data/sttmconfigs/{template_type}', convention)
        if upload_status is not None:
            if upload_status == "issue1":
                st.error("STTM Sheet filename is already in use. Please rename and reupload.")
            elif upload_status == "issue2":
                st.error(f"Filename must start with '{convention}'. Please rename and reupload.")
            else:
                st.success(upload_status)
                st.rerun()

    onlyfiles = read_files_in_folder_dropdown(sttmconfigs_path, template_type)
    selected_sttmfile = st.selectbox(
        "Choose one from STTM Files below...",
        onlyfiles, index=None, placeholder="type to search",
    )

    extra_prompt = None

    if selected_sttmfile is not None:
        st.write("You selected: ", selected_sttmfile)
        if checkbox := st.checkbox("Add prompt explain business requirement?", value=False):
            extra_prompt = st.text_area('Enter text here: ', '')
        st.divider()
        if st.button("Generate SQL Queries based on STTM"):
            with st.spinner('Getting results from AI, Please wait...'):
                response = generate_sql_using_sttm(selected_sttmfile, template_type, extra_prompt)
            st.divider()
            if response is not None:
                st.write(response)  # Display LLM output content
                st.success("Source and Target Queries Generated above.")
            else:
                st.error("Unable to generate SQLs. Please check configs in excel and retry.")


if __name__ == "__main__":

    for folder in input_template_folders:
        folder_name = str(folder).lower()
        path = os.path.join(sttmconfigs_path, folder_name)
        os.makedirs(path, exist_ok=True)

    sql_sttm_generation()
