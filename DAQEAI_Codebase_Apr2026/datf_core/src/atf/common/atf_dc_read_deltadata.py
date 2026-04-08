from pyspark.sql.functions import *
from pyspark.sql.types import *
import math as m
from atf.common.atf_common_functions import log_info, get_mount_path, readconnectionconfig
from testconfig import *
import re

def read_deltadata(tc_datasource_config, spark):
  log_info("Reading delta Data")
  connectionname = tc_datasource_config['connectionname']
  connectiontype = tc_datasource_config['connectiontype']
  resourceformat = tc_datasource_config['format']
  connectionconfig = readconnectionconfig(connectionname)
  resourcename = tc_datasource_config['filename']
  comparetype = tc_datasource_config['testquerygenerationmode']

  #tc_datasource_config['targetfilepath']
  log_info(f"Resource Name - {resourcename}")
  alias_name = tc_datasource_config['aliasname']
  log_info(f"Alias Name - {alias_name}")

  datafilter = tc_datasource_config['filter']
  excludecolumns = tc_datasource_config['excludecolumns']
  excludecolumns = str(excludecolumns)
  exclude_cols = excludecolumns.split(',')
  datafilter = str(datafilter)

  if '/' in tc_datasource_config['filepath']:
    log_info("Inside /")
    deltatable = tc_datasource_config['filepath'].replace('/','.')
    deltatable = re.sub(r'^[.]+|[.]+$', '', deltatable)
  elif len( tc_datasource_config['filepath']) > 0 and '/' not in tc_datasource_config['filepath']:
    deltatable = tc_datasource_config['filepath'] + tc_datasource_config['filename']
  elif len( tc_datasource_config['filepath']) == 0:
    deltatable = tc_datasource_config['filename']

  log_info(f"Delta Table Path - {deltatable}")
  df = spark.table(deltatable)
  df.createOrReplaceTempView(alias_name)
  
  if tc_datasource_config['comparetype'] == 's2tcompare' and tc_datasource_config['testquerygenerationmode'] == 'Auto':
    pass   
    
  elif tc_datasource_config['comparetype'] == 's2tcompare' and tc_datasource_config['testquerygenerationmode'] == 'Manual':
    deltatable = deltatable.replace('/','.')
    querypath = root_path+tc_datasource_config['querypath']
    with open(querypath, "r") as f:
      query_delta= f.read().splitlines()
    query_delta=' '.join(query_delta)
    querydelta = query_delta.replace(alias_name,deltatable)
    log_info(f"Select Table Command statement - \n{querydelta}")

  elif tc_datasource_config['comparetype'] == 'likeobjectcompare':
    log_info('Inside likeobjectcompare code')
    columns = df.columns
    columnlist = list(set(columns) - set(exclude_cols))
    columnlist.sort()
    columnlist = ','.join(columnlist)

    query_delta = "SELECT " + columnlist + " FROM "+ alias_name
    querydelta = query_delta.replace(alias_name,deltatable)

    if len(datafilter) >=5:
      query= query + " WHERE " + datafilter

  log_info(f"Select Table Command statement - \n{querydelta}")
  df_deltadata = spark.sql(querydelta)
  
  df_deltadata.printSchema()
  log_info("Returning the Delta DataFrame")

  return df_deltadata, querydelta