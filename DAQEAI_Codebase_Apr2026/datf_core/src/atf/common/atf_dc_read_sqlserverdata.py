from pyspark.sql.functions import *
from pyspark.sql.types import *
from atf.common.atf_common_functions import log_info,readconnectionconfig
from testconfig import decryptcredential


def read_sqlserverdata(tc_datasource_config,spark):
  log_info("Reading from Sql Server Table")
  connectionname = tc_datasource_config['connectionname']
  connectiontype = tc_datasource_config['connectiontype']
  resourceformat = tc_datasource_config['format']
  connectionconfig = readconnectionconfig(connectionname)
  resourcename = tc_datasource_config['filename']

  connectionurl="jdbc:sqlserver://"+connectionconfig['host']+":"+connectionconfig['port']\
                +";databaseName="+connectionconfig['database']+";encrypt=false;"

  df = (spark.read
              .format("jdbc")
              .option("driver","com.microsoft.sqlserver.jdbc.SQLServerDriver")
              .option("url", connectionurl)
              .option("user", connectionconfig['user'])
              .option("password", decryptcredential(connectionconfig['password']))
              .option("dbtable", resourcename)
              .load())
  columns = df.columns
  columnlist = list(set(columns) - set(tc_datasource_config['excludecolumns'].split(",")))
  columnlist.sort()
  df_data = df.select(columnlist)
  columnlist_str = ','.join(columnlist)
  query = "SELECT " + columnlist_str + f" FROM {resourcename}"
  df_data.printSchema()
  df_data.show()
  log_info("Returning the DataFrame from read_mysqldata Function")
  
  return df_data, query