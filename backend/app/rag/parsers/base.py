"""解析器公共异常。"""

from __future__ import annotations


class ParseError(Exception):
    """文件无法解析/没有可用文字；消息可直接展示给用户。"""