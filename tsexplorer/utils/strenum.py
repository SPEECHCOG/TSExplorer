"""
This module defines a quick StrEnum implementation. In versions 3.11+, the stdlib
contains an implementation for this, and in those cases that implementation should
be used instead.
"""
import enum
from typing import Any, Tuple, Mapping


class StrEnum(str, enum.Enum):
    '''
    Defines a String based enum. Allows one to compare values of the enum
    directly with strings, and thus can be used as an (almost) drop-in
    replacement for module level string constants. Implementation inspired by
    https://github.com/irgeek/StrEnum
    '''
    def __new__(
            cls, value: Any, *args: Tuple[Any, ...],
            **kwargs: Mapping[str, Any]
            ):
        if not isinstance(value, (str, enum.auto)):
            raise TypeError(
                    "StrEnum values must be strings! "
                    f"{value!r} is a {type(value)}"
            )
        return super().__new__(cls, value, *args, **kwargs)

    def __str__(self) -> str:
        ''' Defines a string representation for values'''
        return str(self.value)

    def __repr__(self) -> str:
        ''' Defines repr formatting for the values'''
        return f"'{str(self.value)}'"

    def _generate_next_value_(name: str, *_) -> str:
        ''' Support for auto-generating names'''
        return name
