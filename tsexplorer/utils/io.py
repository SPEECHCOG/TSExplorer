''' This module defines routines for handling any kind of IO required in the
application'''

from ..metadata import Path

import pathlib
import functools
import re
import pickle
import csv
from typing import Tuple, Union, Any, Mapping, Callable, List, Dict, Optional

import io
import numpy as np
import numpy.typing as npt
import pandas as pd
from ruamel.yaml import YAML


def validate_path(
        valid_suffixes: List[str], allow_missing: bool = False
) -> None:

    def _decorator(fn: Callable):
        @functools.wraps(fn)
        def _wrapper_impl(*args: Tuple[Any, ...], **kwargs: Mapping[str, Any]):

            # If there is no filepath, let the function raise the error
            if len(args) < 1:
                return fn(*args, **kwargs)
            fpath = args[0]

            # File descriptors are passed straight to the function
            if isinstance(fpath, io.IOBase):
                return fn(*args, **kwargs)

            # Otherwise the object must be a pathlike
            if not isinstance(fpath, (str, pathlib.PurePath)):
                raise TypeError(("Filepath must be either a string or a "
                                f"pathlib.Path, but got {type(fpath)} instead"))

            fpath = pathlib.Path(fpath)

            if not allow_missing and (not fpath.exists() or not fpath.is_file()):
                raise FileNotFoundError(
                        f"{str(fpath)!r} doesn't point a valid file"
                )

            if fpath.suffix not in valid_suffixes:
                raise ValueError((f"Invalid filetype {fpath.suffix!r}! The "
                                  "supported filetype are "
                                  f"{', '.join(valid_suffixes)}"))

            return fn(*args, **kwargs)
        return _wrapper_impl
    return _decorator


@validate_path(valid_suffixes=[".pickle"])
def load(filepath: Path) -> Any:
    '''
    Loads any previously serialized Python objects from disk.

    Parameters
    ----------
    filepath: Path
        Path to the serialized object.

    Returns
    -------
    Any
        The loaded Python object
    '''
    if isinstance(filepath, io.IOBase):
        return pickle.load(filepath)
    fpath = pathlib.Path(filepath)
    with fpath.open('rb') as fin:
        return pickle.load(fin)


@validate_path(valid_suffixes=[".npy", ".npz"])
def load_numpy(
        filepath: Path, encoding: str = 'ASCII', **kwargs: Mapping[str, Any]
        ) -> npt.NDArray:
    '''
    Loads a numerical file compressed by numpy, and returns the resulting
    array.

    Parameters
    ----------
    filepath: Path
        The path to the file. Should be either a '.npy' or '.npz' file.
    encoding: str, optional
        The encoding used to read the file. Should be one of 'ASCII', 'latin-1'
        or 'bytes'. Default 'ASCII'.
    kwargs: Mapping[str, Any]
        Any possible keyword arguments
    Raises
    ------
    FileNotFoundError
        If the given path doesn't point to a valid file.
    ValueError
        If the path doesn't point to a file with supported format.

    Returns
    -------
    npt.NDArray
        The array containing the data from the file.
    '''
    if isinstance(filepath, io.IOBase):
        return np.load(filepath, allow_pickle=True)
    fpath = pathlib.Path(filepath)
    allow_pickle = kwargs.pop('allow_pickle', True)
    return np.load(fpath, allow_pickle=allow_pickle, **kwargs)


def save_numpy(path, array):
    np.save(path, array)



@validate_path(valid_suffixes=['.yaml', '.yml'])
def load_yaml(filepath: Path) -> Dict[str, Any]:
    '''
    Reads a YAML formatted file, and returns it as a Python dict.

    Parameters
    ----------
    filepath: Path
        The filepath to the file containing the data. Should be either a .yaml
        or .yml file.

    Raises
    ------
    FileNotFoundError
        If the given path doesn't point to a valid file.
    ValueError
        If the path doesn't point to a file with supported format.

    Returns
    -------
    Dict[str, Any]
        The loaded data as a python dict. Note that if custom types are loaded,
        they must be in the scope of the current interpreter session

    '''
    yaml = YAML()
    if isinstance(filepath, io.IOBase):
        return yaml.load(filepath)

    fpath = pathlib.Path(filepath)
    with fpath.open('r') as fin:
        cfg = yaml.load(fin)
    return cfg


@validate_path(valid_suffixes=[".wav"])
def load_wav(filepath: Path) -> Tuple[int, npt.NDArray]:
    '''
    Loads a wav file from a given path.

    Parameters
    ----------
    filepath: Path
        Path to the file to load. Must be a .wav file.

    Raises
    ------
    FileNotFoundError
        If the given path doesn't point to a valid file.
    ValueError
        If the path doesn't point to a file with supported format.

    Returns
    -------
    Tuple[int, npt.NDArray]
        The sampling rate of the signal, and the signal itself
    '''
    from scipy.io import wavfile
    sr, data = wavfile.read(filepath)

    # SO: https://stackoverflow.com/a/26716031
    # If the datatype is integer, convert it to a floating point presentation
    # Where the values are between (-1, 1)
    if issubclass(data.dtype.type, np.integer):
        n_bits = data.dtype.itemsize*8
        max_nb_bits = float(2**(n_bits - 1))
        data = data / (max_nb_bits + 1)
    return sr, data


@validate_path(valid_suffixes=[".csv"])
def load_csv(filepath: Path, **kwargs: Mapping[str, Any]) -> pd.DataFrame:
    '''
    Loads a csv file from a given filepath.

    Parameters
    ----------
    filepath: Path
        the path to the file where the file should be written to. Must be a
        '.csv' file
    **kwargs: Mapping[str, Any]
        Any possible keyword arguments are that are passed to pandas.read_csv

    Raises
    ------
    FileNotFoundError
        If the given path doesn't point to a valid file.
    ValueError
        If the path doesn't point to a file with supported format.

    Returns
    -------
    pd.DataFrame
        A dataframe containing the information from the dataset.
    '''
    return pd.read_csv(filepath, **kwargs)


@validate_path(valid_suffixes=[".pickle"], allow_missing=True)
def dump(filepath: Path, payload: Any) -> None:
    '''
    Serialize any 'picklable' python object to a file.

    Parameters
    ----------
    filepath: Path
        Path to the serialization location.
    payload: Any
        The object to serialize
    '''
    fpath = pathlib.Path(filepath)
    with fpath.open('wb') as fout:
        pickle.dump(payload, fout)


@validate_path(valid_suffixes=['.yaml', '.yml'], allow_missing=True)
def dump_yaml(filepath: Path, payload: Mapping[str, Any]) -> None:
    '''
    Writes a mappable object to a given file. Supports YAML 1.1
    TODO: Add support for serializing numpy arrays as human readable format

    Parameters
    ----------
    filepath: Path
        The path to the file where the data should be written to.
    payload: Mapping[str, Any]
        The data to be written. Should be convertable to YAML.
        If possible, use pure python types where possible.

    Raises
    ------
    ValueError
        If the filepath doesn't point to a YAML file (.yaml or .yml)

    '''
    yaml = YAML()
    fpath = pathlib.Path(filepath)
    with fpath.open('w') as fin:
        yaml.dump(payload, fin)


@validate_path(valid_suffixes=[".csv"], allow_missing=True)
def dump_csv_raw(
        filepath: Path, payload: Mapping[str, List[Any]], *,
        metadata: Optional[List[str]] = None):
    '''
    Writes the given payload as "raw", does not modify the data in any way
    before writing it.

    Parameters
    ----------
    filepath: Path
        Path to the file where the data will be written to.
    payload: Mapping[str, List[Any]]
        The data to load. Each key should correspond to a column in the file,
        while each item under that key should be a list containing the value
        for that column for each row.
    metadata: Optional[List[str]]
        Metadata to write at the top of the file. This could be .e.g. comments.
        Each item in this list is written to its own line. Default None.
    '''
    fpath = pathlib.Path(filepath)
    with fpath.open('w') as ofstream:
        if metadata is not None:
            for row in metadata:
                ofstream.write(f"{row}\n")

        col_names = list(payload.keys())
        writer = csv.DictWriter(ofstream, col_names)

        # Write the actual header
        writer.writeheader()
        # Get the amount of samples
        n_items = len(payload[col_names[0]])
        for i in range(n_items):
            row = {col: payload[col][i] for col in col_names}
            writer.writerow(row)


@validate_path(valid_suffixes=[".csv"], allow_missing=True)
def dump_csv(
        filepath: Path, payload: Mapping[Any, Any],
        orient: str = "index", **kwargs: Mapping[str, Any]
        ):
    '''
    Writes a given 'mappable' object (such as dict) to a csv.

    Parameters
    ----------
    filepath: Path
        The path to the file where the data should be written to
    payload: Mapping[Any, Any]
        The data to be written. Should be convertable to csv.
    orient: str, optional
        The orient that is used when converting the dict to dataframe. Default
        'index'
    **kwargs: Mapping[str, Any]
        Any possible keywords for the pandas.to_csv method.

    Raises
    ------
    ValueError
        If the filepath doesn't point to a csv file
    '''
    df = pd.DataFrame.from_dict(payload, orient=orient)
    df.to_csv(filepath, **kwargs)


@validate_path(valid_suffixes=[".npy"], allow_missing=True)
def dump_npy(filepath: Union[Path, io.IOBase], data: npt.NDArray):
    '''
    Writes the given numpy array to a .npy file.

    Parameters
    ----------
    filepath: Path | io.IOBase
        Path to the file where the data will be stored.
        If this is an open file-descriptitor, it must be writable (in binary)

    data: npt.NDArray
        The data to write. Can be any array/object that can be serialized by
        numpy
    '''
    if isinstance(filepath, io.IOBase):
        np.save(filepath, data)
        return

    fpath = pathlib.Path(filepath)
    with fpath.open('wb') as fout:
        np.save(fout, data)


def rm_dir(fpath: Path):
    '''
    Recursively deletes a directory, and its contents.

    Parameters
    ----------
    fpath: Path
        Path to the directory to delete.
    '''
    fpath = pathlib.Path(fpath)
    if not fpath.is_dir():
        raise NotADirectoryError(("Expected a path to a directory, "
                                  f"but got {str(fpath)!r}"))
    for item in fpath.iterdir():
        if item.is_dir():
            rm_dir(item)
        else:
            item.unlink(missing_ok=True)
    fpath.rmdir()
