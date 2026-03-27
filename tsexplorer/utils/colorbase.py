from typing import Dict, List

_DEFAULT_COLORS: Dict[str, List[str]] = {
        "default":  [
            '#0b06b8', '#ffea00', '#048013', '#0b06b8', '#911eb4', '#e61919', '#46f0f0', '#aa6e28',
            '#000000', '#ff82f8', '#d2f53c', '#fabebe', '#008080', '#e6beff', '#20b2aa', '#800000',
            '#aaffc3', '#ffd8b1', '#000080', '#808080', '#a9a9a9', '#ff69b4', '#ff1493', '#808000',
            '#f58231', '#b0e0e6', '#ff4500', '#7fffd4', '#dc143c', '#00ced1', '#dda0dd'
            ],
        "waveform_default":  [
            '#0b06b8', '#e61919', '#048013', '#0b06b8', '#911eb4', '#ffea00', '#46f0f0', '#aa6e28',
            '#000000', '#ff82f8', '#d2f53c', '#fabebe', '#008080', '#e6beff', '#20b2aa', '#800000',
            '#aaffc3', '#ffd8b1', '#000080', '#808080', '#a9a9a9', '#ff69b4', '#ff1493', '#808000',
            '#f58231', '#b0e0e6', '#ff4500', '#7fffd4', '#dc143c', '#00ced1', '#dda0dd'
            ],
        "ggplot": [
            # Blue
            '#348ABD', '#7A68A6', '#A60628', '#467821', '#CF4457', '#188487',
            '#E24A33'
            ]
}



def get_colors(cmap: str = "default") -> List[str]:
    '''
    Retrieve the color list for a given colormap

    Parameters
    ----------
    cmap: str
        The name of the colormap.

    Returns
    -------
    List[str]
        The list of colors used in that colormap.
    '''
    if cmap not in _DEFAULT_COLORS:
        raise KeyError((f"Unknown colormap {cmap!r}! Supported colormaps: "
                        f"{', '.join(_DEFAULT_COLORS.keys())}"))

    return _DEFAULT_COLORS[cmap]
