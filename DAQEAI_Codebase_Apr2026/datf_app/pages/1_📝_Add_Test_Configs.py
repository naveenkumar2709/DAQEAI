import streamlit as st
from datf_app.common.commonmethods import *


def _get_config_options(selected_protocol):
    """Read dropdown options from the protocol Excel config sheet."""
    protocol_path = f"{tc_path}/{selected_protocol}"
    defaults = {
        "comparetype": ["likeobjectcompare", "s2tcompare"],
        "querygenerationmode": ["Auto", "Manual"],
        "yesorno": ["Y", "N"],
        "fileformat": ["table", "parquet", "delimited", "avro", "json", "delta"],
        "connectiontype": [
            "databricks", "aws-s3", "adls", "gcp-gcs", "snowflake", "bigquery", 
            "redshift", "oracle", "mysql", "sqlserver", "postgres", "teradata", "db2"
        ],
    }
    try:
        config_df = pd.read_excel(protocol_path, sheet_name="config")
        for key in defaults:
            if key in config_df.columns:
                values = config_df[key].dropna().astype(str).str.strip().tolist()
                cleaned = list(dict.fromkeys([v for v in values if v]))
                if cleaned:
                    defaults[key] = cleaned
    except Exception:
        pass
    return defaults


def _get_next_sno(df):
    """Return the next serial number based on existing rows."""
    if "Sno." in df.columns and len(df) > 0:
        try:
            return int(df["Sno."].max()) + 1
        except Exception:
            pass
    return len(df) + 1


def _opt_select(label, options, key, help=None):
    """Selectbox with an empty first option (treated as None on save)."""
    return st.selectbox(label, [""] + options, key=key, help=help)


def add_test_case_page():
    st.set_page_config(page_title="Add Test Config")
    st.logo(logo_path)
    st.title("Add New Test Config")

    onlyfiles = read_test_protocol()
    selected_protocol = st.selectbox(
        "Choose a Test Protocol...",
        onlyfiles, index=None, placeholder="type to search",
    )

    if selected_protocol is None:
        st.info("Select a test protocol to continue.")
        return

    opts = _get_config_options(selected_protocol)

    # Load existing rows (needed for Sno. calculation and concat on save)
    try:
        existing_df = pd.read_sql_query(
            f"SELECT * FROM '{selected_protocol}'", conn_exe
        )
    except Exception:
        existing_df = pd.DataFrame()

    st.caption(f"Protocol currently has **{len(existing_df)}** test case(s).")

    # ── Outside form: fields whose values drive conditional rendering ────────
    qm_src_col, qm_tgt_col = st.columns(2)
    with qm_src_col:
        sourcequerymode = _opt_select("Source Query Mode", opts["querygenerationmode"], "src_qmode")
    with qm_tgt_col:
        targetquerymode = _opt_select("Target Query Mode", opts["querygenerationmode"], "tgt_qmode")

    ff_src_col, ff_tgt_col = st.columns(2)
    with ff_src_col:
        sourcefileformat = _opt_select("Source File Format", opts["fileformat"], "src_file_fmt")
    with ff_tgt_col:
        targetfileformat = _opt_select("Target File Format", opts["fileformat"], "tgt_file_fmt")

    _src_is_manual    = st.session_state.get("src_qmode")    == "Manual"
    _tgt_is_manual    = st.session_state.get("tgt_qmode")    == "Manual"
    _src_is_delimited = st.session_state.get("src_file_fmt") == "delimited"
    _tgt_is_delimited = st.session_state.get("tgt_file_fmt") == "delimited"

    with st.form("add_test_case_form", clear_on_submit=True):

        # ── Test Case Info ────────────────────────────────────────────
        st.subheader("Test Case Info")
        c1, c3 = st.columns([3, 2])
        with c1:
            test_case_name = st.text_input("Test Case Name *", key="tcname")
        with c3:
            comparetype = st.selectbox(
                "Compare Type", opts["comparetype"], key="comparetype"
            )

        testquerygenerationmode = (
            "Manual"
            if (st.session_state.get("src_qmode") == "Manual" or st.session_state.get("tgt_qmode") == "Manual")
            else "Auto"
        )
        c4, c2 = st.columns([2, 4])
        with c4:
            st.text_input("Query Generation Mode", value=testquerygenerationmode, disabled=True)
        with c2:
            execute = st.checkbox("Execute?", value=False, key="execute")

        st.divider()

        # ── Source & Target ───────────────────────────────────────────
        src_col, tgt_col = st.columns(2)

        with src_col:
            st.subheader("Source")
            sourcealiasname         = st.text_input("Alias Name",         key="src_alias")
            sourceconnectionname    = st.text_input("Connection Name",     key="src_conn_name")
            sourceconnectiontype    = _opt_select("Connection Type",  opts["connectiontype"],    "src_conn_type")
            sourcefilepath          = st.text_input("File Path",           key="src_file_path",
                                                    help="Leave blank if file format is table")
            sourcefilename          = st.text_input("File/Table Name",           key="src_file_name")
            if _src_is_delimited:
                sourcefilehasheader = _opt_select("Has Header", opts["yesorno"], "src_hdr")
                sourcefiledelimiter = st.text_input("Delimiter",           key="src_delim")
            else:
                sourcefilehasheader = None
                sourcefiledelimiter = None
            sourcefilter            = st.text_input("Filter",              key="src_filter")
            sourceexcludecolumnlist = st.text_input("Exclude Column List", key="src_excl",
                                                     help="Comma-separated column names to exclude")
            if _src_is_manual:
                sourcequerysqlpath     = st.text_input("SQL File Path", key="src_sql_path")
                sourcequerysqlfilename = st.text_input("SQL File Name", key="src_sql_file")
            else:
                sourcequerysqlpath     = None
                sourcequerysqlfilename = None

        with tgt_col:
            st.subheader("Target")
            targetaliasname         = st.text_input("Alias Name",         key="tgt_alias")
            targetconnectionname    = st.text_input("Connection Name",     key="tgt_conn_name")
            targetconnectiontype    = _opt_select("Connection Type",  opts["connectiontype"],    "tgt_conn_type")
            targetfilepath          = st.text_input("File Path",           key="tgt_file_path",
                                                    help="Leave blank if file format is table")
            targetfilename          = st.text_input("File/Table Name",           key="tgt_file_name")
            if _tgt_is_delimited:
                targetfilehasheader = _opt_select("Has Header", opts["yesorno"], "tgt_hdr")
                targetfiledelimiter = st.text_input("Delimiter",           key="tgt_delim")
            else:
                targetfilehasheader = None
                targetfiledelimiter = None
            targetfilter            = st.text_input("Filter",              key="tgt_filter")
            targetexcludecolumnlist = st.text_input("Exclude Column List", key="tgt_excl",
                                                     help="Comma-separated column names to exclude")
            if _tgt_is_manual:
                targetquerysqlpath     = st.text_input("SQL File Path", key="tgt_sql_path")
                targetquerysqlfilename = st.text_input("SQL File Name", key="tgt_sql_file")
            else:
                targetquerysqlpath     = None
                targetquerysqlfilename = None

        st.divider()

        # ── Mapping & Others ──────────────────────────────────────────
        st.subheader("Mapping & Others")
        m1, m2, m3 = st.columns(3)
        with m1:
            s2tpath          = st.text_input("S2T Mapping File Path",  key="s2tpath")
            s2tmappingsheet  = st.text_input("S2T Mapping Sheet Name", key="s2tsheet")
        with m2:
            primarykey       = st.text_input("Primary Key",            key="pk",
                                              help="Comma-separated if multiple keys")
        with m3:
            samplelimit      = st.number_input("Sample Limit",      min_value=0, value=0,    step=1, key="samplelimit")
            dataprofilelimit = st.number_input("Data Profile Limit", min_value=0, value=1000, step=1, key="dplimit")

        submitted = st.form_submit_button("Add Test Case", type="primary", use_container_width=True)

    if submitted:
        if not test_case_name.strip():
            st.error("Test Case Name is required.")
            return

        if (
            not existing_df.empty
            and "test_case_name" in existing_df.columns
            and test_case_name.strip() in existing_df["test_case_name"].astype(str).str.strip().values
        ):
            st.error(f"Test case name **{test_case_name.strip()}** already exists. Please use a unique name.")
            return

        def _val(v):
            """Return None for empty strings."""
            return v if v else None

        new_row = {
            "Sno.":                    _get_next_sno(existing_df),
            "test_case_name":          test_case_name.strip(),
            "execute":                 execute,
            "comparetype":             _val(comparetype),
            "testquerygenerationmode": _val(testquerygenerationmode),
            # Source
            "sourcealiasname":         _val(sourcealiasname),
            "sourceconnectionname":    _val(sourceconnectionname),
            "sourceconnectiontype":    _val(sourceconnectiontype),
            "sourcefileformat":        _val(sourcefileformat),
            "sourcefilepath":          _val(sourcefilepath),
            "sourcefilename":          _val(sourcefilename),
            "sourcefilehasheader":     _val(sourcefilehasheader),
            "sourcefiledelimiter":     _val(sourcefiledelimiter),
            "sourcefilter":            _val(sourcefilter),
            "sourceexcludecolumnlist": _val(sourceexcludecolumnlist),
            "sourcequerymode":         _val(sourcequerymode),
            "sourcequerysqlpath":      _val(sourcequerysqlpath),
            "sourcequerysqlfilename":  _val(sourcequerysqlfilename),
            # Target
            "targetaliasname":         _val(targetaliasname),
            "targetconnectionname":    _val(targetconnectionname),
            "targetconnectiontype":    _val(targetconnectiontype),
            "targetfileformat":        _val(targetfileformat),
            "targetfilepath":          _val(targetfilepath),
            "targetfilename":          _val(targetfilename),
            "targetfilehasheader":     _val(targetfilehasheader),
            "targetfiledelimiter":     _val(targetfiledelimiter),
            "targetfilter":            _val(targetfilter),
            "targetexcludecolumnlist": _val(targetexcludecolumnlist),
            "targetquerymode":         _val(targetquerymode),
            "targetquerysqlpath":      _val(targetquerysqlpath),
            "targetquerysqlfilename":  _val(targetquerysqlfilename),
            # Mapping
            "s2tpath":                 _val(s2tpath),
            "s2tmappingsheet":         _val(s2tmappingsheet),
            "primarykey":              _val(primarykey),
            "samplelimit":             int(samplelimit),
            "dataprofilelimit":        int(dataprofilelimit),
        }

        try:
            updated_df = pd.concat(
                [existing_df, pd.DataFrame([new_row])],
                ignore_index=True,
            )
            save_df_into_db(updated_df, selected_protocol)
            st.success(f"Test case **{test_case_name.strip()}** added successfully!")
            st.rerun()
        except Exception as e:
            st.error(f"Failed to save: {e}")


if __name__ == "__main__":
    add_test_case_page()
