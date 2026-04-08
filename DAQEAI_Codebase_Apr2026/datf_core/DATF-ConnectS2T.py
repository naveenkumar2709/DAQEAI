# Databricks notebook source
dbutils.widgets.text('test_protocol', 'test_databricksprotocol')
dbutils.widgets.text("test_case", "testcase12_parquet_parquet_mismatch_manual")
dbutils.widgets.text('work_path', '/Workspace/Shared/DAQEAI/')

# COMMAND ----------

work_path = dbutils.widgets.get("work_path")
install_path = f"{work_path}/requirements.txt"
%pip install -r $install_path

# COMMAND ----------

dbutils.library.restartPython()

# COMMAND ----------

#python
import os
work_path = dbutils.widgets.get("work_path")
os.environ['CWD'] = work_path
py_file = f"{work_path}/datf_core/src/connections2t.py"
test_case = dbutils.widgets.get("test_case")
test_protocol = dbutils.widgets.get("test_protocol")
params = {
    "test_protocol": test_protocol,
    "test_case": test_case
}
test_protocol = f"{work_path}/datf_core/test/testprotocol/{test_protocol}.xlsx"
runner = f"{py_file} {test_protocol} {test_case}"
%run $runner
