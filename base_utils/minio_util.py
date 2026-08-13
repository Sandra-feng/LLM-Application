#!/usr/bin/env python
# -*- coding: UTF-8 -*-
"""
@Project ：tiance-base
@File    ：minio_util.py
@Author  ：TaoMeng
@Date    ：2024/8/27 10:14
"""

from typing import Optional
from minio import Minio, S3Error
from base_configs.minio_config import MinioConfig
from minio.api import CopySource


# 新增工具仓储
from data_access.implementations.minio_repository import MinioRepository

# 创建一个minio的单例实例。
# 用于导入静态MongodbUtil类的应用程序的所有部分
# 现在将得到这个实例，它符合相同的接口。
# 后续 todolist需要根据.env配置文件来动态创建实例
class _MinioUtilFacade:
    """
    一个外观类，充当实际 MinioRepository 实例的全局代理。
    它允许业务逻辑代码继续使用 MinIoUtil.method() 的方式调用，
    而实例的生命周期则在 main.py 中集中管理。
    """
    _client: "MinioRepository" = None

    def initialize(self, client: "MinioRepository"):
        """在应用启动时由 main.py 调用，注入真实的客户端实例。"""
        self._client = client

    def __getattr__(self, name):
        """
        当访问 MinIoUtil 的任何属性时（如 upload_file），
        此方法会将调用转发给内部持有的真实 _client 实例。
        """
        if self._client is None:
            raise RuntimeError(
                "MinIoUtil has not been initialized. "
                "Ensure it is initialized in the FastAPI lifespan."
            )
        return getattr(self._client, name)

MinIoUtil = _MinioUtilFacade()


# class MinIoUtil(object):
#     """
#     MinIo工具类
#     """

#     # 客户端
#     min_io_client = None

#     @staticmethod
#     def connect():
#         """
#         连接
#         :return:
#         """
#         MinIoUtil.min_io_client = Minio(
#             endpoint=MinioConfig.END_POINT,
#             access_key=MinioConfig.ACCESS_KEY,
#             secret_key=MinioConfig.SECRET_KEY,
#             secure=False,
#         )

#     @staticmethod
#     def reconnect():
#         """
#         重新连接MinIo
#         :return:
#         """
#         MinIoUtil.min_io_client = None
#         MinIoUtil.connect()

#     @staticmethod
#     def create_bucket(bucket_name):
#         """
#         Create a bucket
#         :param bucket_name: Bucket name
#         :return:
#         """
#         if not MinIoUtil.min_io_client.bucket_exists(bucket_name=bucket_name):
#             MinIoUtil.min_io_client.make_bucket(bucket_name=bucket_name)

#             policy = """{{
#                 "Version": "2012-10-17",
#                 "Statement": [
#                     {{
#                         "Effect": "Allow",
#                         "Principal": "*",
#                         "Action": "s3:GetObject",
#                         "Resource": "arn:aws:s3:::{bucket_name}/*"
#                     }}
#                 ]
#             }}""".format(
#                 bucket_name=bucket_name
#             )

#             MinIoUtil.min_io_client.set_bucket_policy(bucket_name, policy)

#     @staticmethod
#     def remove_bucket(bucket_name):
#         """
#         删除存储桶
#         :param bucket_name: 存储桶名称
#         :return:
#         """
#         MinIoUtil.min_io_client.remove_bucket(bucket_name=bucket_name)

#     @staticmethod
#     def upload_file(bucket_name, remote_path, local_path, data: Optional[dict] = None):
#         """
#         上传文件
#         :param bucket_name: 存储桶名称
#         :param remote_path: 远程文件路径
#         :param local_path: 本地文件路径
#         :return:
#         """
#         MinIoUtil.min_io_client.fput_object(
#             bucket_name=bucket_name,
#             object_name=remote_path,
#             file_path=local_path,
#             metadata=data,
#         )

#     @staticmethod
#     def upload_image_file(
#         bucket_name, remote_path, local_path, data: Optional[dict] = None
#     ):
#         """
#         上传文件
#         :param bucket_name: 存储桶名称
#         :param remote_path: 远程文件路径
#         :param local_path: 本地文件路径
#         :return:
#         """
#         MinIoUtil.min_io_client.fput_object(
#             bucket_name=bucket_name,
#             object_name=remote_path,
#             file_path=local_path,
#             metadata=data,
#             content_type="image/png",
#         )

#     @staticmethod
#     def download_file(bucket_name, remote_path, local_path):
#         MinIoUtil.min_io_client.fget_object(
#             bucket_name=bucket_name, object_name=remote_path, file_path=local_path
#         )

#     @staticmethod
#     def get_file_list(bucket_name, prefix):
#         """
#         获取文件列表
#         :param bucket_name: 存储桶名称
#         :param prefix: 前缀(必须要以“/结尾”)
#         :return:
#         """
#         file_list = list()
#         object_list = MinIoUtil.min_io_client.list_objects(
#             bucket_name=bucket_name, prefix=prefix
#         )
#         for obj in object_list:
#             file_list.append(obj.object_name)
#         return file_list

#     @staticmethod
#     def get_file_url(bucket_name, log_path):
#         """
#         获取文件下载链接
#         :param bucket_name: 存储桶名称
#         :param log_path: 日志路径
#         :return: 文件链接
#         """
#         presigned_url = MinIoUtil.min_io_client.presigned_get_object(
#             bucket_name, log_path
#         )
#         return presigned_url

#     @staticmethod
#     def copy_object(source_bucket, source_object, target_bucket, target_object):
#         copy_source = CopySource(source_bucket, source_object)
#         MinIoUtil.min_io_client.copy_object(target_bucket, target_object, copy_source)

#     @staticmethod
#     def remove_file(bucket_name, file_name, file_path: str = ""):
#         """
#         删除文件
#         :param bucket_name: 存储桶名称
#         :param remote_path: 远程文件路径
#         :return:
#         """
#         remote_path = f"{file_path}/{file_name}" if file_path else f"pytest/{file_name}"
#         MinIoUtil.min_io_client.remove_object(bucket_name, remote_path)

#     @staticmethod
#     def delete_file(bucket_name, file_path):
#         """
#         删除文件
#         :param bucket_name: 存储桶名称
#         :param remote_path: 远程文件路径
#         :return:
#         """
#         remote_path = f"{file_path}"
#         MinIoUtil.min_io_client.remove_object(bucket_name, remote_path)

#     @staticmethod
#     def exist_file(bucket_name, file_path):
#         """
#         判断文件是否存在
#         :param bucket_name: 存储桶名称
#         :param file_path: 远程文件路径
#         """
#         try:
#             MinIoUtil.min_io_client.stat_object(
#                 bucket_name=bucket_name, object_name=file_path
#             )
#             return True
#         except S3Error as e:
#             if e.code == "NoSuchKey":
#                 return False
#             raise

#     @staticmethod
#     def is_prefix_exist(bucket_name: str, prefix: str) -> bool:
#         """检查指定前缀下是否存在至少一个文件"""
#         try:
#             # 确保前缀以 "/" 结尾（若需匹配文件夹结构）
#             normalized_prefix = prefix if prefix.endswith("/") else f"{prefix}/"
#             objects = MinIoUtil.min_io_client.list_objects(
#                 bucket_name, prefix=normalized_prefix
#             )
#             return any(obj.object_name for obj in objects)
#         except S3Error as e:
#             if e.code == "NoSuchBucket":
#                 return False
#             raise


if __name__ == "__main__":
    minioutil = MinIoUtil
    minioutil.connect()
    minioutil.create_bucket("pytest")

    # 下载文件
    # r_p = "2024/08/27/audio/模型管理接口-20240826.xmind"
    # l_p = "./模型管理接口-20240826.xmind"
    # MinIoUtil.download_file(b_n, r_p, l_p)
