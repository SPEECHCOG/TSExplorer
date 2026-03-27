'''This module defines types & custom exceptions used in the application'''
from .utils.strenum import StrEnum

from enum import IntEnum
from enum import unique
from typing import NewType, Union
import os
import pathlib

# Type for file IDs
SampleID = NewType("SampleID", int)

# Alias for Path types
Path = Union[str, os.PathLike]

# Alias for 'strictly' real number
Real = Union[int, float]


# Path to the template configuration
TEMPLATE_CONFIG_PATH: pathlib.Path = (
        pathlib.Path(__file__).parent / "configs" / "template_config.yml"
    )


@unique
class SampleState(StrEnum):
    '''
    Defines all possible states that a Sample can have at any given time.
    '''
    UNLABELED = "unlabeled"
    SELECTED  = "selected"
    ANNOTATED = "annotated"


@unique
class WidgetType(StrEnum):
    '''
    Defines all currently used widget types
    '''
    SCATTER    = "scatter"
    SPECTROGRAM = "spectrogram"
    WAVEFORM   = "waveform"
    AUDIO      = "audio"
    VIDEO      = "video"


@unique
class MediaPlayerState(IntEnum):
    '''
    Defines all possible states that a MediaPlayer can have
    '''
    STOPPED = 0
    PLAYING = 1
    PAUSED  = 2


class SQLException(Exception):
    """
    Raised when any error happens in SQL operations
    """
    pass
