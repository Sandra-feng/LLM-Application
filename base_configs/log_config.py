#!/usr/bin/env python
"""
@File         :log_config.py
@Description  :基于 Loguru 的日志配置模块（使用 logrotate 进行日志轮转）
@Author       :zhou_min
@Date         :2025/09/11
@Update       :2025/10/09 - 移除自定义轮转逻辑，使用系统 logrotate 工具
"""

import logging
import re
import sys
import traceback
from pathlib import Path
import sys
from loguru import logger
from rich.console import Console
from rich.logging import RichHandler

# 统一的日志格式，用于应用中的所有日志记录
LOG_FORMAT = (
    "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
    "<level>{level: <8}</level> | "
    "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>"
    "<red>{extra[exception_hint]}</red>"
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT_STR = str(PROJECT_ROOT)
MAX_TRACEBACK_FRAMES = 5


class SafeConsole(Console):
    """
    一个安全的 Console 类，用于覆盖默认的 on_broken_pipe 行为。

    rich.Console 的默认行为是在检测到 BrokenPipeError 时引发 SystemExit，
    这会导致在非交互式环境（如 systemd 服务）中程序意外退出。
    我们通过重写 on_broken_pipe 方法来阻止这种行为。
    """

    def on_broken_pipe(self) -> None:
        """在管道断开时什么也不做，而不是退出程序。"""
        pass


class StaticFileFilter:
    """静态文件请求过滤器"""

    # 静态文件路径前缀
    STATIC_PREFIXES = ("/static/", "/assets/", "/favicon.ico", "/.well-known/")
    # 静态文件后缀
    STATIC_SUFFIXES = (
        ".css",
        ".js",
        ".map",
        ".png",
        ".jpg",
        ".jpeg",
        ".svg",
        ".ico",
        ".woff",
        ".woff2",
        ".ttf",
        ".eot",
        ".mjs",
        ".json",
    )
    # HTTP访问日志正则表达式
    ACCESS_LOG_REGEX = re.compile(r'(\d+\.\d+\.\d+\.\d+):\d+ - "(\w+) ([^"]+) HTTP/\d\.\d" \d+')

    @classmethod
    def should_filter(cls, record: logging.LogRecord) -> bool:
        """判断是否应该过滤此日志记录"""
        try:
            # 检查记录器名称
            if record.name in ("uvicorn.access", "uvicorn.error"):
                # 对于uvicorn访问日志，解析路径
                message = record.getMessage()
                match = cls.ACCESS_LOG_REGEX.search(message)
                if match:
                    method, path = match.group(2), match.group(3)
                    # 过滤静态资源请求
                    if any(path.startswith(prefix) for prefix in cls.STATIC_PREFIXES):
                        return True
                    if any(path.endswith(suffix) for suffix in cls.STATIC_SUFFIXES):
                        return True
                    # 过滤OPTIONS请求（通常是CORS预检请求）
                    if method == "OPTIONS":
                        return True
                return False

            # 对于其他日志，检查消息内容
            message = record.getMessage()
            if any(prefix in message for prefix in cls.STATIC_PREFIXES):
                return True
            if any(suffix in message for suffix in cls.STATIC_SUFFIXES):
                return True

            return False
        except Exception:
            # 发生异常时不过滤，避免误伤
            return False


class InterceptHandler(logging.Handler):
    """
    标准日志拦截处理器。

    拦截来自标准 logging 模块（如 Uvicorn、SQLAlchemy）的日志，
    并将其重定向到 Loguru 进行统一处理和格式化。
    """

    def emit(self, record: logging.LogRecord) -> None:
        # 先检查是否应该过滤此日志
        if StaticFileFilter.should_filter(record):
            return

        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        frame, depth = logging.currentframe(), 2
        while frame and frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1

        logger.opt(depth=depth, exception=record.exc_info).log(level, record.getMessage())


def setup_logging():
    """
    配置并初始化全局 Loguru 日志记录器。

    注意：日志轮转现在由系统 logrotate 工具处理，而不是应用代码。
    此函数应在应用程序启动时调用一次。
    """
    logger.remove()

    # 定义一个过滤器，用于在控制台输出中排除请求上下文日志
    def console_filter(record):
        # 如果日志记录的名称是 "observability.request_context"，则不显示在控制台
        return record["name"] != "observability.request_context"

    # 定义一个 patcher：过滤第三方库堆栈，只保留项目相关代码
    def conditional_exception_patcher(record):
        record["extra"].setdefault("exception_hint", "")

        # 如果没有异常，直接返回
        exception = record["exception"]
        if not exception:
            return

        exc_type, exc_value, exc_tb = exception

        if exc_tb is None:
            formatted = "".join(traceback.format_exception_only(exc_type, exc_value)).rstrip()
            record["extra"]["exception_hint"] = f"\n{formatted}"
            record["exception"] = None  # 清空原始异常
            return

        # 提取所有堆栈帧
        extracted_frames = traceback.extract_tb(exc_tb)

        # 分离项目代码帧和第三方库帧
        project_frames = []
        project_frame_indices = []

        for idx, frame in enumerate(extracted_frames):
            try:
                resolved = Path(frame.filename).resolve()
            except Exception:
                resolved = Path(frame.filename)

            if str(resolved).startswith(PROJECT_ROOT_STR):
                project_frames.append(frame)
                project_frame_indices.append(idx)

        # 如果没有项目帧，保留最后几帧作为上下文
        if not project_frames:
            project_frames = extracted_frames[-MAX_TRACEBACK_FRAMES:]
        else:
            # 如果有项目帧，添加第一个项目帧之前的最后一帧（入口点）
            if project_frame_indices and project_frame_indices[0] > 0:
                entry_frame = extracted_frames[project_frame_indices[0] - 1]
                project_frames.insert(0, entry_frame)

        # 为文件日志和控制台准备简化的堆栈信息
        formatted_tb = "".join(traceback.format_list(project_frames))
        formatted_exc = "".join(traceback.format_exception_only(exc_type, exc_value))
        trimmed_exception = f"{formatted_tb}{formatted_exc}".rstrip()

        # 统一使用 exception_hint（文件日志和控制台都用这个）
        record["extra"]["exception_hint"] = f"\n{trimmed_exception}"

        # 清空原始异常，避免重复显示
        record["exception"] = None

    logger.configure(patcher=conditional_exception_patcher)

    # 确保日志目录存在
    log_dir = Path("logs")
    log_dir.mkdir(parents=True, exist_ok=True)

    # Sink 1: 控制台输出（使用 Rich）
    # 关闭 rich_tracebacks，使用 patcher 生成的简化堆栈（已过滤第三方库）
    # 检查是否在终端环境中，如果不是则使用更安全的配置
    is_terminal = sys.stdout.isatty() if hasattr(sys.stdout, "isatty") else False
    console = SafeConsole(
        force_terminal=is_terminal,  # 只在真正的终端中强制终端模式
        color_system="auto",
        width=None,
        file=sys.stderr,  # 使用 stderr 作为输出，更安全
        legacy_windows=False,
    )
    logger.add(
        RichHandler(
            console=console,
            rich_tracebacks=False,  # 关闭自动堆栈，使用过滤后的版本
            tracebacks_show_locals=False,
            show_time=True,
            show_level=True,
            show_path=True,
            markup=True,
        ),
        level="INFO",
        format="{message}{extra[exception_hint]}",  # 控制台也显示 exception_hint
        filter=console_filter,
    )

    # logger.add(
    #     sys.stdout,
    #     level="INFO",
    #     format=LOG_FORMAT,
    #     colorize=True,
    #     enqueue=True,  # 进程安全
    #     filter=console_filter,  # 应用过滤器
    #     catch=True,  # 捕获异常，防止日志写入失败导致程序崩溃
    # )

    # Sink 2: INFO 级别文件日志
    # 使用 loguru 标准文件写入，轮转完全由 logrotate 处理
    logger.add(
        "logs/tiance-base.log",
        level="INFO",
        format=LOG_FORMAT,
        enqueue=True,  # 进程安全
        encoding="utf-8",
        rotation=None,  # 禁用 loguru 自动轮转，完全由 logrotate 处理
        retention=None,  # 禁用 loguru 自动清理，完全由 logrotate 处理
        catch=False,  # 不捕获异常，让我们自己处理
    )

    # Sink 3: ERROR 级别文件日志
    # 使用 loguru 标准文件写入，轮转完全由 logrotate 处理
    logger.add(
        "logs/tiance-base-error.log",
        level="ERROR",
        format=LOG_FORMAT,
        enqueue=True,  # 进程安全
        encoding="utf-8",
        rotation=None,  # 禁用 loguru 自动轮转，完全由 logrotate 处理
        retention=None,  # 禁用 loguru 自动清理，完全由 logrotate 处理
        catch=False,
    )

    # 完全拦截所有标准日志记录器
    logging.basicConfig(handlers=[InterceptHandler()], level=0, force=True)

    # 特别处理Uvicorn相关的日志记录器
    uvicorn_loggers = ["uvicorn", "uvicorn.access", "uvicorn.error", "uvicorn.asgi"]

    for logger_name in uvicorn_loggers:
        uvicorn_logger = logging.getLogger(logger_name)
        uvicorn_logger.handlers = [InterceptHandler()]
        uvicorn_logger.propagate = False
        uvicorn_logger.setLevel(logging.INFO)

    # 处理其他可能产生重复日志的记录器
    other_loggers = ["fastapi", "sqlalchemy", "pymysql", "httpx"]

    for logger_name in other_loggers:
        other_logger = logging.getLogger(logger_name)
        other_logger.handlers = [InterceptHandler()]
        other_logger.propagate = False
        other_logger.setLevel(logging.WARNING)  # 只记录WARNING及以上级别

    logger.info("日志模块初始化完成")
