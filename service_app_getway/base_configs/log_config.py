
import os

# 获取项目的绝对路径
BASE_DIR = os.path.dirname(os.path.abspath(os.path.dirname(__file__)))


class LogConfig(object):
    """
    日志文件配置
    """
    # 日志文件目录
    LOG_DIR = os.path.join(BASE_DIR, 'logs')
    # 日志配置
    if not os.path.exists(LOG_DIR):
        os.makedirs(LOG_DIR)
    LOG_FORMAT = '[%(asctime)s] [%(name)s %(process)d] [%(module)s.%(funcName)s: %(lineno)d] %(levelname)s: %(message)s'
    LOG_LEVEL = 'debug'
    MAX_BYTES = 100 * 1024 * 1024  # 100M
    BACKUP_COUNT = 30
    WHEN = 'D'

