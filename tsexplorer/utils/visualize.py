''' This module contains utility functions for visualizations'''

import matplotlib as mpl

import numpy as np
import numpy.typing as npt

_SEQ_CMAP: str = "magma"
_BOOL_CMAP: str = "gray_r"
_DIV_CMAP: str = "coolwarm"


def get_cmap(
        data: npt.NDArray, robust: bool =True, seq_cmap: str = "magma",
        div_cmap: str = "coolwarm"
        ) -> str:
    '''
    Gets the colormap based on the given data. If the data contains both
    negative and positive values, diverging colormap is used. Otherwise,
    sequential colormap is selected.

    Parameters
    ----------
    data: npt.NDArray
        The data for which the colormap is chosen.
    robust: bool, optional
        If set to True, the bottom/top 2 percent of values are not considered.
        Otherwise, all values are considered. Default True
    seq_cmap: str, optional
        The used sequential colormap. Must be a valid matplotlib colormap name.
        Default "magma".
    div_cmap: str, optional
        The used diverging colormap. Must be a valid matplotlib colormap name.

    Returns
    -------
    str
        The identifier for the chosen colormap
    '''
    data = data[np.isfinite(data)]  # Remove any inf values.

    min_p, max_p = (2, 98) if robust else (0, 100)
    # Calculate the percentile from 2 to 98 percent.
    min_val, max_val = np.percentile(data, [min_p, max_p])

    if min_val >= 0 or max_val <= 0:
        return mpl.colormaps[seq_cmap]
    return mpl.colormaps[div_cmap]


def frames_to_time(frames: npt.NDArray, *, sr, hop_ms=10) -> npt.NDArray:
    # 250 frames, each frame 30 ms, hop_ms = 10 ms
    return frames / (sr - hop_ms)
    
