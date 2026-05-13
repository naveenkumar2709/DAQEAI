#!/usr/bin/env python
# encoding: utf-8
"""
testconfig.py
"""
import os
import ssl
os.environ["NODE_TLS_REJECT_UNAUTHORIZED"] = "0"
os.environ["PYTHONHTTPSVERIFY_SSL"] = "0"
os.environ["PYARROW_IGNORE_TIMEZONE"] = "1"
ssl._create_default_https_context = ssl._create_unverified_context
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
import warnings
warnings.simplefilter(action='ignore', category=FutureWarning)
warnings.simplefilter(action='ignore', category=DeprecationWarning)
import pytz
import json
from cryptography.fernet import Fernet

# *** Initial Configuration ***
protocol_engine = "databricks-free" # options: databricks, databricks-free, docker
database_engine = "default" # options: default, *snowflake, *delta

if "databricks" in protocol_engine.lower() and os.getenv('CWD') is not None:
    root_path = os.getenv('CWD') + "/datf_core/"
elif protocol_engine == "docker":
    root_path = "datf_core/"
else:
    root_path = "datf_core/"

print("Root Path = " + root_path)

# *** DO NOT CHANGE BELOW VALUES ***
allowed_extensions = ['pdf', 'docx', 'xlsx', 'jpg', 'jpeg', 'png']
utctimezone = pytz.timezone("UTC")
results_db_name = 'DATF_RESULTS'
rept_table_name = 'historical_trends'
exec_db_name = 'DATF_EXECUTION'
exec_table_name = 'testselection'
exec_sheet_name = 'protocoltestcasedetails'
protocol_tab_name = 'protocol'
connections_path = f"{root_path}test/connections"
genai_conn_json = "ai_qe_config_keys.json"
tc_path = f"{root_path}test/testprotocol"
sqlbulk_path = f"{root_path}test/sqlbulk"
sttmconfigs_path = f"{root_path}test/data/sttmconfigs"
bulkresults_path = f"{root_path}test/results/bulkresults"
output_file_path = f"{root_path}test/testprotocol/{exec_table_name}_template.xlsx"
profile_output_path = f"{root_path}test/results/profiles"
column_data_path = f"{root_path}test/data/columndata"
src_column_path = f"{column_data_path}/source_columns.xlsx"
tgt_column_path = f"{column_data_path}/target_columns.xlsx"
gen_queries_path = f"{column_data_path}/generated_queries.json"
dq_testconfig_path = f"{column_data_path}/current_testconfig.json"
dq_data_path = f"{root_path}test/data/dqconfig"
dq_result_path = f"{root_path}test/results/dataquality"
logo_path = "datf_app/common/tiger_analytics_nobg.png"
# bi reconciliation results file locations
bi_results_path = f"{root_path}test/results/bi_data"
bi_step1_path = bi_results_path + "/1_graphdata/"
bi_step2_path = bi_results_path + "/2_backenddata/"
bi_step3_path = bi_results_path + "/3_comparison/"

# create the folders for results if not exist
os.makedirs(sqlbulk_path, exist_ok=True)
os.makedirs(sttmconfigs_path, exist_ok=True)
os.makedirs(bulkresults_path, exist_ok=True)
os.makedirs(profile_output_path, exist_ok=True)
os.makedirs(column_data_path, exist_ok=True)
os.makedirs(dq_data_path, exist_ok=True)
os.makedirs(dq_result_path, exist_ok=True)
os.makedirs(bi_step1_path, exist_ok=True)
os.makedirs(bi_step2_path, exist_ok=True)
os.makedirs(bi_step3_path, exist_ok=True)

with open(f"{connections_path}/{genai_conn_json}", "r+") as json_file:
    openai_json = json.load(json_file)
os.environ["AZURE_OPENAI_API_KEY"] = openai_json['ai_apikey']
os.environ["AZURE_OPENAI_ENDPOINT"] = openai_json['ai_endpoint']
os.environ["OPENAI_API_KEY"] = openai_json['ai_apikey']
os.environ["OPENAI_BASE_URL"] = openai_json['ai_endpoint']
os.environ["DATABRICKS_HOST"] = openai_json['databricks_url']
os.environ["DATABRICKS_TOKEN"] = openai_json['databricks_token']

spark_conf_JSON = """ {
    "spark.executor.instances": "18",
    "spark.executor.cores": "8",
    "spark.executor.memory": "6g",
    "spark.default.parallelism": "56",
    "spark.sql.shuffle.partitions": "250",
    "spark.memory.offHeap.enabled": "true",
    "spark.memory.offHeap.size": "2g",
    "spark.memory.fraction": "0.8",
    "spark.memory.storageFraction": "0.6",
    "spark.sql.debug.maxToStringFields": "300",
    "spark.sql.legacy.timeParserPolicy": "LEGACY",
    "spark.sql.autoBroadcastJoinThreshold": "-1",
    "spark.sql.execution.arrow.pyspark.enabled": "true"
} """


def decryptcredential(encodedstring):
    cryptokey = b'K_QLpmYNUy6iHP4m73k2Q2brMfFy2nmJJK61HlSOTQI='
    encrypted = str.encode(encodedstring)
    fer = Fernet(cryptokey)
    decrypted = fer.decrypt(encrypted).decode('utf-8')
    return decrypted

