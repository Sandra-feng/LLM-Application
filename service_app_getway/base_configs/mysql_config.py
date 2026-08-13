class MySQLConfig(object):
    """
    mongodb配置信息
    """

    # mongodb配置
    MySQL_HOST = "10.8.21.166"
    MySQL_PORT = 3306
    MySQL_USER = "root"
    MySQL_PASS = "Admin%402024"
    MySQL_DB = "tiance_base_dev"



class TableConfig(object):
    """
    表信息
    """

    # 账号信息
    USR_TABLE = "user_info"
    ROLE_TABLE = "role_info"
    RES_TABLE = "res_info"
    CONFIG_TABLE = "config_info"
    ROLE_RES_TABLE = "role_res_relation"
    ROLE_MEM_TABLE = "role_mem_relation"
    ACC_TOKEN_TABLE = "account_token"