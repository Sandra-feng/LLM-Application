from enum import Enum
class ModelType(Enum):
    LLM = 'LLM'
    EMBEDDIND = 'embedding'
    RE_RANK = 'rerank'
    IMAGE_MODEL = 'image'
    AUDIO = 'audio'
    VIDEO = 'video'

    @classmethod
    def value_of(cls, value: str) -> 'ModelType':
        """
        Get value of given mode.

        :param value: mode value
        :return: mode
        """
        for mode in cls:
            if mode.value == value:
                return mode
        raise ValueError(f'invalid mode value {value}')