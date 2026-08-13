

class XinferenceConfig(object):
    """
    API配置
    """
    SERVICE_IP = "10.8.21.164"

    # 配置服务端口
    SERVICE_PORT = 9997

    # xinference所在服务器用户
    SERVER_USER = "root"

    # xinference所在服务器密码
    SERVER_PASSWORD = "LcGSQb8bfA#wHmY0C)cB"

    # xinference所在服务ssh端口
    SSH_PORT = 22

    # xinference 可执行程序位置：conda远程调用会有问题，先采用绝对路径
    XINFERENCE_CMD = "/opt/y/envs/xinference/bin/xinference"


