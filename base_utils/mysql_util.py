import pymysql
from sqlalchemy.orm import sessionmaker
from sqlalchemy.exc import DisconnectionError
from base_configs.mysql_config import MySQLConfig
from sqlalchemy import create_engine
import datetime
from sqlalchemy import event
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
import json


pymysql.install_as_MySQLdb()


from sqlalchemy.orm import sessionmaker
from data_access.implementations.mysql_repository import (
    MySQLEngineFactory,
    query2dictid,
    query2dict,
    query2dict_id,
    query2dict_status,
    query2dict_acc
)

# 为了向后兼容，我们创建一个工厂的实例，
# 并将其方法分配给一个模仿旧的静态类结构的新类。
# 这避免了从 `MySQLUtil.creat_engine()` 到 `MySQLUtil().creat_engine()` 的调用变化。
_engine_factory = MySQLEngineFactory()

class MySQLUtil:
    creat_engine = _engine_factory.creat_engine
    creat_async_engine = _engine_factory.creat_async_engine

# SessionLocal 在模块级别创建，依赖于 `MySQLUtil.creat_engine`。
# 我们在这里复制它，以保持任何可能导入它的模块的兼容性。
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=MySQLUtil.creat_engine())



# def query2dictid(model_list, Model):
#     if not model_list:
#         return model_list

#     if isinstance(
#         model_list, list
#     ):  # 如果传入的参数是一个list类型的，说明是使用的all()的方式查询的
#         if isinstance(
#             model_list[0], Model
#         ):  # 这种方式是获得的整个对象  相当于 select * from table
#             lst = []
#             for model in model_list:
#                 dic = {}
#                 for col in model.__table__.columns:
#                     val = getattr(model, col.name)
#                     if isinstance(val, datetime.datetime):
#                         dic[col.name] = datetime.datetime.strftime(
#                             val, "%Y-%m-%d %H:%M:%S"
#                         )
#                     else:
#                         dic[col.name] = val
#                 lst.append(dic)
#             return lst
#         else:  # 这种方式获得了数据库中的个别字段  相当于select id,name from table
#             lst = []
#             for result in model_list:
#                 # 当以这种方式返回的时候，result中会有一个keys()的属性
#                 if isinstance(result.keys, datetime.datetime):
#                     lst.append(
#                         [
#                             dict(
#                                 zip(
#                                     result.keys,
#                                     datetime.datetime.strftime(r, "%Y-%m-%d %H:%M:%S"),
#                                 )
#                             )
#                             for r in result
#                         ]
#                     )
#                 else:
#                     lst.append([dict(zip(result.keys, r)) for r in result])
#             return lst
#     else:  # 不是list,说明是用的get() 或者 first()查询的，得到的结果是一个对象
#         if isinstance(
#             model_list, Model
#         ):  # 这种方式是获得的整个对象  相当于 select * from table limit=1
#             dic = {}
#             for col in model_list.__table__.columns:
#                 val = getattr(model_list, col.name)
#                 if isinstance(val, datetime.datetime):
#                     dic[col.name] = datetime.datetime.strftime(val, "%Y-%m-%d %H:%M:%S")
#                 else:
#                     dic[col.name] = getattr(model_list, col.name)
#             return dic
#         else:  # 这种方式获得了数据库中的个别字段  相当于select id,name from table limit = 1
#             return dict(zip(model_list.keys(), model_list))


# def query2dict(model_list, Model):
#     data = query2dictid(model_list, Model)
#     if not model_list:
#         return model_list

#     if isinstance(data, list):
#         data_list = []
#         for d in data:
#             keys_to_remove = ["id", "status"]
#             d = {key: value for key, value in d.items() if key not in keys_to_remove}
#             data_list.append(d)
#         return data_list
#     else:
#         keys_to_remove = ["id", "status"]
#         data = {key: value for key, value in data.items() if key not in keys_to_remove}
#         return data


# def query2dict_id(model_list, Model):
#     data = query2dictid(model_list, Model)
#     if not model_list:
#         return model_list

#     if isinstance(data, list):
#         data_list = []
#         for d in data:
#             keys_to_remove = ["status"]
#             d = {key: value for key, value in d.items() if key not in keys_to_remove}
#             data_list.append(d)
#         return data_list
#     else:
#         keys_to_remove = ["status"]
#         data = {key: value for key, value in data.items() if key not in keys_to_remove}
#         return data


# def query2dict_status(model_list, Model):
#     data = query2dictid(model_list, Model)
#     if not model_list:
#         return model_list

#     if isinstance(data, list):
#         data_list = []
#         for d in data:
#             keys_to_remove = ["id"]
#             d = {key: value for key, value in d.items() if key not in keys_to_remove}
#             data_list.append(d)
#         return data_list
#     else:
#         keys_to_remove = ["id"]
#         data = {key: value for key, value in data.items() if key not in keys_to_remove}
#         return data


# def query2dict_acc(model_list, Model):
#     data = query2dictid(model_list, Model)
#     if not model_list:
#         return model_list

#     if isinstance(data, list):
#         data_list = []
#         for d in data:
#             keys_to_remove = ["id", "status", "password", "attribute"]
#             d = {key: value for key, value in d.items() if key not in keys_to_remove}
#             data_list.append(d)
#         return data_list
#     else:
#         keys_to_remove = ["id", "status", "password", "attribute"]
#         data = {key: value for key, value in data.items() if key not in keys_to_remove}
#         return data


# class MySQLUtil(object):

#     @staticmethod
#     def creat_engine():
#         DB_URI = (
#             "mysql+pymysql://{username}:{pwd}@{host}:{port}/{db}?charset=utf8".format(
#                 username=MySQLConfig.MySQL_USER,
#                 pwd=MySQLConfig.MySQL_PASS,
#                 host=MySQLConfig.MySQL_HOST,
#                 port=MySQLConfig.MySQL_PORT,
#                 db=MySQLConfig.MySQL_DB,
#             )
#         )
#         engine = create_engine(
#             DB_URI,
#             pool_size=30,
#             max_overflow=-1,  # 允许超出连接池的最大连接数
#             pool_timeout=30,  # 等待连接池中可用连接的超时时间
#             pool_recycle=3600,  # 每 3600 秒回收一次连接
#             pool_pre_ping=True,
#         )

#         # 添加事件监听器用于处理断开连接的重试
#         @event.listens_for(engine, "checkout")
#         def receive_checkout(dbapi_connection, connection_record, connection_proxy):
#             cursor = dbapi_connection.cursor()
#             try:
#                 cursor.execute("SELECT 1")
#             except Exception as e:
#                 # 如果查询失败，则认为连接已失效，关闭旧连接并抛出异常让SQLAlchemy进行重试
#                 dbapi_connection.close()
#                 raise DisconnectionError()

#         return engine

#     @staticmethod
#     def creat_async_engine():
#         DB_URI = (
#             "mysql+asyncmy://{username}:{pwd}@{host}:{port}/{db}?charset=utf8".format(
#                 username=MySQLConfig.MySQL_USER,
#                 pwd=MySQLConfig.MySQL_PASS,
#                 host=MySQLConfig.MySQL_HOST,
#                 port=MySQLConfig.MySQL_PORT,
#                 db=MySQLConfig.MySQL_DB,
#             )
#         )
#         engine = create_async_engine(
#             DB_URI,
#             pool_size=30,
#             max_overflow=-1,
#             pool_timeout=30,
#             pool_recycle=3600,
#             pool_pre_ping=True,
#         )
#         return engine


# SessionLocal = sessionmaker(
#     autocommit=False, autoflush=False, bind=MySQLUtil.creat_engine()
# )


# if __name__ == '__main__':
#     mysqlutil = MySQLUtil()
#     uri = mysqlutil.creat_engine()
#     print(uri)
#     print(MySQLConfig.MySQL_PASS)
#     import pymysql
#     SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=MySQLUtil.creat_engine())


# # 数据库连接配置
# host = "10.8.21.166"        # 数据库主机地址
# port = 3306               # 数据库端口
# user = "root"    # 数据库用户名
# password = "Admin@2024" # 数据库密码
# database = "tiance_base_dev" # 数据库名称

# # 建立连接
# connection = pymysql.connect(
#     host=host,
#     port=port,
#     user=user,
#     password=password,
#     database=database,
#     charset="utf8"
# )
# print("连接成功！")
