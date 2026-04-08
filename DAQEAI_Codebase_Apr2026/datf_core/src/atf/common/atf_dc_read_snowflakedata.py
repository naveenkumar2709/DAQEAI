from pyspark.sql.functions import *
from pyspark.sql.types import *
from atf.common.atf_common_functions import extract_database, log_info, readconnectionconfig
from testconfig import root_path

SNOWFLAKE_SOURCE_NAME = "net.snowflake.spark.snowflake"


def read_snowflakedata(tc_datasource_config, spark):
  log_info("Reading from Snowflake Warehouse")

  connectionname = tc_datasource_config['connectionname']
  connectiontype = tc_datasource_config['connectiontype']
  resourceformat = tc_datasource_config['format']
  connectionconfig = readconnectionconfig(connectionname)
  resourcename = tc_datasource_config['filename']
  databasename = connectionconfig['database']

  if tc_datasource_config['testquerygenerationmode'] == 'Manual':
        querypath = root_path + tc_datasource_config['querypath']
        with open(querypath, "r+") as f:
            selectmanualqry = f.read().splitlines()
        selectmanualqry = ' '.join(selectmanualqry)
        selectmanualqry = str(selectmanualqry)
        print(selectmanualqry)
        selectcolqry_ret = selectmanualqry
        f.close()

        df_snowflakedata = (spark.read.format(SNOWFLAKE_SOURCE_NAME)
                    .option("sfURL", connectionconfig['host'])
                    .option("sfUser", connectionconfig['user'])
                    .option("sfPassword", connectionconfig['password'])
                    .option("sfDatabase", databasename)
                    .option("sfWarehouse", connectionconfig['warehouse'])
                    .option("autopushdown", "on")
                    .option("query", selectmanualqry)
                    .load())
        
        df_out = df_snowflakedata
        
  elif tc_datasource_config['testquerygenerationmode'] == 'Auto':
        datafilter = tc_datasource_config['filter']
        excludecolumns = tc_datasource_config['excludecolumns']
        excludecolumns = str(excludecolumns)
        exclude_cols = excludecolumns.split(',')
        datafilter = str(datafilter)
        selectallcolqry = f"SELECT * FROM {resourcename} "
        if len(datafilter) > 0:
          selectallcolqry = selectallcolqry + datafilter

        df_snowflakedata = (spark.read.format(SNOWFLAKE_SOURCE_NAME)
                          .option("sfURL", connectionconfig['host'])
                          .option("sfUser", connectionconfig['user'])
                          .option("sfPassword", connectionconfig['password'])
                          .option("sfDatabase", databasename)
                          .option("sfWarehouse", connectionconfig['warehouse'])
                          .option("autopushdown", "on")
                          .option("query", selectallcolqry)
                          .load())
  
        columns = df_snowflakedata.columns
        columnlist = list(set(columns) - set(exclude_cols))
        columnlist.sort()
        columnlist = ','.join(columnlist)

        df_snowflakedata.createOrReplaceTempView("snowflakeview")
        selectcolqry = "SELECT " + columnlist + " FROM snowflakeview"
        selectcolqry_ret = "SELECT " + columnlist + f" FROM {resourcename}"
        df_out = spark.sql(selectcolqry)

  df_out.printSchema()
  df_out.show()
  log_info("Returning the DataFrame from read_snowflakedata Function")
  return df_out, selectcolqry_ret