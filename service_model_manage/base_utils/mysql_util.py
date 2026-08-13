import pymysql
from sqlalchemy.orm import  sessionmaker
from service_app_getway.base_configs.mysql_config import MySQLConfig
from sqlalchemy import create_engine
import datetime



pymysql.install_as_MySQLdb()


def query2dictid(model_list,Model):
    if not model_list:
        return model_list

    if isinstance(model_list,list):  #如果传入的参数是一个list类型的，说明是使用的all()的方式查询的
        if isinstance(model_list[0],Model):   # 这种方式是获得的整个对象  相当于 select * from table
            lst = []
            for model in model_list:
                dic = {}
                for col in model.__table__.columns:
                    val = getattr(model,col.name)
                    if isinstance(val,datetime.datetime):
                        dic[col.name] = datetime.datetime.strftime(val,'%Y-%m-%d %H:%M:%S')
                    else:
                        dic[col.name] = val
                lst.append(dic)
            return lst
        else:                           #这种方式获得了数据库中的个别字段  相当于select id,name from table
            lst = []
            for result in model_list:
                #当以这种方式返回的时候，result中会有一个keys()的属性
                if isinstance(result.keys, datetime.datetime):
                    lst.append([dict(zip(result.keys, datetime.datetime.strftime(r,'%Y-%m-%d %H:%M:%S'))) for r in result])
                else:
                    lst.append([dict(zip(result.keys, r)) for r in result])
            return lst
    else:                   #不是list,说明是用的get() 或者 first()查询的，得到的结果是一个对象
        if isinstance(model_list,Model):   # 这种方式是获得的整个对象  相当于 select * from table limit=1
            dic = {}
            for col in model_list.__table__.columns:
                val = getattr(model_list, col.name)
                if isinstance(val, datetime.datetime):
                    dic[col.name] = datetime.datetime.strftime(val, '%Y-%m-%d %H:%M:%S')
                else:
                    dic[col.name] = getattr(model_list,col.name)
            return dic
        else:    #这种方式获得了数据库中的个别字段  相当于select id,name from table limit = 1
            return dict(zip(model_list.keys(),model_list))

def query2dict(model_list,Model):
    data = query2dictid(model_list,Model)
    if not model_list:
        return model_list

    if isinstance(data,list):
        data_list = []
        for d in data:
            keys_to_remove = ["id", "status"]
            d={key: value for key, value in d.items() if key not in keys_to_remove}
            data_list.append(d)
        return data_list
    else:
        keys_to_remove = ["id","status"]
        data ={key: value for key, value in data.items() if key not in keys_to_remove}
        return data

def query2dictstatus(model_list,Model):
    data = query2dictid(model_list,Model)
    if not model_list:
        return model_list

    if isinstance(data,list):
        data_list = []
        for d in data:
            keys_to_remove = ["id"]
            d={key: value for key, value in d.items() if key not in keys_to_remove}
            data_list.append(d)
        return data_list
    else:
        keys_to_remove = ["id"]
        data ={key: value for key, value in data.items() if key not in keys_to_remove}
        return data

def query2dict_acc(model_list,Model):
    data = query2dictid(model_list,Model)
    if not model_list:
        return model_list

    if isinstance(data,list):
        data_list = []
        for d in data:
            keys_to_remove = ["id", "status","password","attribute"]
            d={key: value for key, value in d.items() if key not in keys_to_remove}
            data_list.append(d)
        return data_list
    else:
        keys_to_remove = ["id", "status","password","attribute"]
        data ={key: value for key, value in data.items() if key not in keys_to_remove}
        return data

class MySQLUtil(object):

    @staticmethod
    def creat_engine():
        DB_URI = 'mysql+pymysql://{username}:{pwd}@{host}:{port}/{db}?charset=utf8' \
            .format(username=MySQLConfig.MySQL_USER, pwd=MySQLConfig.MySQL_PASS, host=MySQLConfig.MySQL_HOST,
                    port=MySQLConfig.MySQL_PORT, db=MySQLConfig.MySQL_DB)
        return create_engine(DB_URI,
                             pool_size=30,        # 设置连接池大小
                             max_overflow=20,     # 设置最大溢出连接数
                             pool_timeout=30,     # 设置获取连接的超时时间（秒）
                             pool_recycle=1800    # 设置连接回收时间（秒），防止连接被数据库服务器关闭)
                            )


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=MySQLUtil.creat_engine())

def quick_sort(li, start, end, index):
    """ 排序"""
    if start >= end:
        return
    low = start
    hight = end
    mid = li[low][index]
    mid_all = li[low]
    while low < hight:
        while low < hight and li[hight][index] < mid:  # <
            hight -= 1
        li[low] = li[hight]
        while low < hight and li[low][index] >= mid:  # >=
            low += 1
        li[hight] = li[low]
    li[low] = mid_all
    quick_sort(li, start, low - 1, index)
    quick_sort(li, low + 1, end, index)

if __name__ == '__main__':
    print('1')


