'''
This file contains some global configuration options (e.g. default window
size, font-size, font-color etc.). This is done in a way that is completely
separate from other parts of the project.
'''

import pathlib
import collections.abc
import copy

from typing import Dict, Any, Mapping

from ruamel.yaml import YAML

_CONFIG_PATH: pathlib.Path = (
        pathlib.Path(__file__).parent / "configs" / "defaults.yml"
    ).resolve()

RCPARAMS: Dict[str, Any] = None


def _read_config(filepath: pathlib.Path) -> Dict[str, Any]:
    '''
    Reads the configuration file. If this function fails to find the config,
    one should notify the user and halt the operation.
    '''

    if not filepath.exists() or not filepath.is_file():
        raise FileNotFoundError(("Cannot find configuration file from "
                                f"{filepath!r}"))

    yaml = YAML()
    with filepath.open('r') as fin:
        cfg = yaml.load(fin)
    return cfg


def reload_config() -> None:
    global RCPARAMS
    RCPARAMS = _read_config(_CONFIG_PATH)


def update_rcparams(payload: Dict[str, str]):
    '''
    Updates the global RCPARAMS

    Parameters
    ----------
    payload: Dict[str, str]
        The updated values
    '''
    global RCPARAMS

    def _update(to_update: Mapping, updated_vals: Mapping) -> Mapping:
        '''
        Recursive update of any depth dicts. Differs from the default dict
        update in the sense that if updated values are missing keys, they are not
        removed from the original dict

        Parameters
        ----------
        to_update: Mapping
            The key-value map to update. May contain nested mappings.
        updated_vals: Mapping
            The update values. May contain nested mappings.

        Returns
        -------
        Mapping
            The updated values
        '''
        for k, v in updated_vals.items():
            if isinstance(v, collections.abc.Mapping):
                to_update[k] = _update(to_update.get(k, {}), v)
            else:
                to_update[k] = v
        return to_update

    tmp_copy = copy.deepcopy(RCPARAMS)
    _update(tmp_copy, payload)
    RCPARAMS = tmp_copy


RCPARAMS = _read_config(_CONFIG_PATH)
