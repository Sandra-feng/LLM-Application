import aioredis
from typing import AsyncGenerator
from fastapi import Depends, HTTPException
from base_configs import redis_config



# 新增
from data_access.implementations.redis_repository import RedisRepository

# 创建 RedisRepository 的单例实例。
# 所有以前导入 RedisUtil 类的部分现在都会获取这个实例，
# 它符合相同的接口。
RedisUtil = RedisRepository()



# class RedisUtil(object):
#     # Redis
#     @staticmethod
#     async def get_redis_pool() -> AsyncGenerator[aioredis.Redis, None]:
#         """
#         创建并返回 Redis 连接池。通过依赖注入管理 Redis 连接池。
#         """
#         redis = await aioredis.create_redis_pool(
#             (redis_config.REDIS_HOST, redis_config.REDIS_PORT),
#             db=redis_config.REDIS_DB,
#             password=redis_config.PASSWORD,
#             encoding="utf-8",
#             minsize=redis_config.REDIS_POOL_MIN_SIZE,  # 设置最小连接数
#             maxsize=redis_config.REDIS_POOL_MAX_SIZE,  # 设置最大连接数
#         )
#         return redis

#     @staticmethod
#     async def cache_data(
#         key: str, value: str, redis: aioredis.Redis, expire_seconds: int = 36000
#     ):
#         """
#         设置缓存数据
#         """
#         try:
#             await redis.set(key, value, expire=expire_seconds)
#             return {"message": "Data cached successfully", "key": key, "value": value}
#         except Exception as e:
#             raise HTTPException(status_code=404, detail=f"cache_data error:{e}")

#     @staticmethod
#     async def cache_data_static(key: str, value: str, redis: aioredis.Redis):
#         """
#         设置静态缓存数据
#         """
#         try:
#             await redis.set(key, value)
#             return {"message": "Data cached successfully", "key": key, "value": value}
#         except Exception as e:
#             raise HTTPException(status_code=404, detail=f"cache_data error:{e}")

#     @staticmethod
#     async def get_cached_data(key: str, redis: aioredis.Redis):
#         """
#         获取缓存数据
#         """
#         try:
#             value = await redis.get(key)
#             if value is None:
#                 return None
#             return {"key": key, "value": value}
#         except Exception as e:
#             raise HTTPException(status_code=404, detail=f"cache_data error:{e}")

#     @staticmethod
#     async def delete_cached_data(key: str, redis: aioredis.Redis):
#         """
#         删除缓存数据
#         """
#         try:
#             result = await redis.delete(key)
#             if result == 0:
#                 return None
#             return {"message": f"Data with key {key} deleted successfully"}
#         except Exception as e:
#             raise HTTPException(status_code=400, detail=f"str{e}")

#     @staticmethod
#     async def close_redis(redis: aioredis.Redis):
#         redis.close()
#         await redis.wait_closed()


async def main():
    # 创建 Redis 连接池
    redis = await aioredis.create_redis_pool(
        (redis_config.REDIS_HOST, redis_config.REDIS_PORT),
        db=redis_config.REDIS_DB,
        password=redis_config.PASSWORD,
        encoding="utf-8",
        minsize=redis_config.REDIS_POOL_MIN_SIZE,  # 设置最小连接数
        maxsize=redis_config.REDIS_POOL_MAX_SIZE,  # 设置最大连接数
    )

    try:
        # 从 Redis 中获取值
        # value = await redis.get("API_Whitelist")
        # print("Value from Redis:", value)
        # result = await redis.delete("Api_Whitelist")
        # print("Value from Redis:", result)
        # result = await redis.delete("API_Whitelist")
        keys = await redis.keys("*")
        for key in keys:
            value = await redis.get(key)
            print(f"Key: {key}, Value: {value}")
        # result = await redis.delete("API_Whitelist")
    finally:
        # 关闭 Redis 连接池
        redis.close()
        await redis.wait_closed()


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
