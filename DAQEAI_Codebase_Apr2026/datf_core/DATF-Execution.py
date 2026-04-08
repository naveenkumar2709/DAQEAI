# Databricks notebook source
dbutils.widgets.text('test_protocol_name', 'test_databricksprotocol')
dbutils.widgets.dropdown("test_type", "count", ['count', 'null', 'duplicate', 'fingerprint', 'content', 'schema'])
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
py_file = f"{work_path}/datf_core/src/s2ttester.py"
test_type = dbutils.widgets.get("test_type")
test_protocol_name = dbutils.widgets.get("test_protocol_name")
params = {
    "test_protocol_name": test_protocol_name,
    "test_type": test_type
}
test_protocol = f"{work_path}/datf_core/test/testprotocol/{test_protocol_name}.xlsx"
runner = f"{py_file} {test_protocol} {test_type}"
%run $runner

# COMMAND ----------

work_path = dbutils.widgets.get("work_path")
html_file_content = open(f"{work_path}/datf_core/utils/reports/datfreport.html", 'r').read()
displayHTML(html_file_content)

# COMMAND ----------

work_path = dbutils.widgets.get("work_path")
html_file_content = open(f"{work_path}/datf_core/utils/reports/datf_trends_report.html", 'r').read()
displayHTML(html_file_content)
