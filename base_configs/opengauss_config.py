class OpengaussConfig(object):
    """
    opengauss配置信息
    """

    # mongodb配置
    Opengauss_HOST = "222.240.16.132"
    Opengauss_PORT = 5432
    Opengauss_USER = "omm"
    Opengauss_PASS = "Huawei_110120"  # 真实密码 Admin@2024
    Opengauss_DB = "postgres"
    DEFAULT_MILVUS_OUTPUT_FIELDS = ["content", "number", "file_name", "file_time"]
    DEFAULT_ALL_FIELDS = ["index", "file_name", "file_id", "file_time", "number", "content", "vector", "question", "source_data"]