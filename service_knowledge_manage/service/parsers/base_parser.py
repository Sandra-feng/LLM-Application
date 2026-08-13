from abc import ABC, abstractmethod
from typing import Any


class BaseParser(ABC):
    """
    文件解析器的抽象基类
    """

    @abstractmethod
    async def parse(self, file_path: str, **kwargs) -> dict[str, Any]:
        """
        解析文件并提取内容。

        Args:
            file_path (str): 要解析的文件的路径。
            **kwargs: 其他特定于解析器的参数。

        Returns:
            Dict[str, Any]: 一个包含解析结果的字典，至少应包含:
                - 'text' (str): 提取出的纯文本内容。
                - 'metadata' (List[Dict]): 每个文档块或页面的元数据列表。
        """
        pass
