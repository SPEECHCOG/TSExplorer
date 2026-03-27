from ..metadata import Real

import functools
import warnings
import sys
import pathlib
import json

from typing import Callable, Union, Tuple, List, Mapping, Any
import numpy.typing as npt

import numpy as np


def deprecated(msg: str):
    '''
    Mark a function/class/method as deprecated. Will raise a
    deprecation warning, using the given message regardless of the used
    filter warnings.

    Parameters
    ----------
    msg: str
        The message to show along the deprecation
    '''

    def decorator(fn: Callable):
        fmt_msg = "{name} is deprecated: {msg}"

        @functools.wraps(fn)
        def _wraps(*args, **kwargs):
            # Ensure that the warning is not silenced
            warnings.simplefilter("always", DeprecationWarning)
            warnings.warn(
                    fmt_msg.format(name=fn.__name__, msg=msg),
                    category=DeprecationWarning,
                    stacklevel=2
            )
            # Restore the previous filter behaviour
            warnings.simplefilter("always", DeprecationWarning)
            return fn(*args, **kwargs)
        return _wraps
    return decorator


def rgba_to_ints(colors: npt.ArrayLike) -> npt.NDArray[np.int64]:
    '''
    Convert floating point representation of colors to integer representation.
    Expects that values are in (0, 1) range, and scales them to
    (0, 255) range.
    '''
    colors = np.asarray(colors)
    if colors.max() > 1.0 or colors.min() < 0.0:
        raise ValueError(("Expected values to be in range (0., 1.), but got "
                          f"({colors.min():2f}, {colors.max():.2f}"))
    return (255*colors).astype(np.int64)


def rgba_to_str(
        rgb: Union[Tuple[int, int, int], Tuple[int, int, int, int]]
        ) -> str:
    '''
    Converts RGBA tuple to a string representation of the given color.

    Parameters
    ----------
    rbg: Tuple[int, int, int] | Tuple[int, int, int, int]
        The RGB(A) color as a tuple. If the tuple contains only 3 values,
        the alpha channel is expected to be missing

    Returns
    -------
    str
        The stringified representation of the color
    '''
    n = len(rgb)
    if n != 3 and n != 4:
        raise ValueError(("Only rgb or rgba tuples are supported! "
                         f"(Received {len(rgb)} components"))
    return f"#{''.join(f'{c:02X}' for c in rgb)}"


def fontsize_to_int(fontsize: str) -> int:
    '''
    Converts a given font size to an integer. NOTE: Extracts the pure integer
    value, and does not take into account the unit of the size
    (e.g. pt, px etc).

    Parameters
    ----------
    fontsize: str
        The font-size as a string, may contain unit descriptor.

    Returns
    -------
    int
        The integer value of the font size.
    '''
    out = ""
    for c in fontsize:
        if c.isnumeric():
            out += c
    try:
        return int(out)
    except ValueError:
        raise ValueError(f"Could not extract font-size from {fontsize!r}")


def clamp(x: Real, xmin: Real, xmax: Real) -> Real:
    '''
    Clamps a given value to be in a given range.
    NOTE: The results will be casted to be same data type as the input variable
    'x'. The result is thus dependent on the casting behaviour of the type.

    Parameters
    ----------
    x: Real
        The parameter to clamp
    xmin: Real
        The minimum allowed value.
    xmax: Real
        The maximum allowed value.
    '''
    outtype = type(x)
    return outtype(max(xmin, min(x, xmax)))


def get_user_data_directory(
        append_paths: Union[str, List[str], Tuple[str, ...]] = None
        ) -> str:

    '''
    Get the user data directory for the given system. The $HOME/user path is
    given by 'pathlib.Path.home'.

    Linux: ~/.local/share
    MacOS: ~/Library/Application Support
    Windows: C:/Users/<USER>/AppData/Roaming

    Inspired by
    https://gist.github.com/jslay88/1fd8a8ba1d05ff2a4810520785a67891


    Parameters
    ----------
    append_paths: str | Iterable[str] | None
        The paths to append to the user data directory. Default None.

    Returns
    -------
    str
        The user data directory. No checks are done to ensure that the
        directory exists
    '''
    from PySide6.QtCore import QStandardPaths

    # This can be empty. In that case use the hard-coded version
    data_path = QStandardPaths.writableLocation(QStandardPaths.AppLocalDataLocation)
    if data_path == "":
        home_path = pathlib.Path.home()
        sys_paths = {
            "win32": home_path / "AppData" / "Roaming",
            "linux": home_path / ".local" / "share",
            "darwin": home_path / "Library" / "Application support"
        }

        # If Qt cannot figure out the path, and we have no hard-coded backup
        # path for the given platform, we just error out
        if sys.platform not in sys_paths:
            raise SystemError(
                (f"Unsupported platform: {sys.platform!r}! "
                 f"Supported platforms: {','.join(sys_paths.keys())}"))

        data_path = sys_paths.get(sys.platform)

    data_path = pathlib.Path(data_path)
    # Ensure that the path does not contain any suffixed ends (Qt adds some
    # garbage to the end of the actual directory path)
    if data_path.suffix != '':
        data_path = data_path.parent

    if append_paths is not None:
        if isinstance(append_paths, str):
            append_paths = [append_paths]
        for path in append_paths:
            data_path /= path
    return data_path


def prettify_map(data: Mapping[Any, Any], sort_keys: bool = False) -> str:
    '''
    Prettifies the string representation of a mapping.

    Parameters
    ----------
    data: Mapping[Any, Any]
        The data to prettify.
    sort_keys: bool, optional
        If set to True, the keys will be sorted alphabetically. Default False.

    Returns
    -------
    str
        The prettified string representation
    '''
    return json.dumps(data, indent=4, sort_keys=sort_keys)
