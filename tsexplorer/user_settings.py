from .utils import io
from .metadata import Path, WidgetType, SampleState

from typing import Any, Union, Mapping, Dict, List
import copy
import pathlib

# For validating the user configuration
from schema import Schema, Regex, Or, And, Optional
from PySide6.QtCore import QObject


# Define schema for the configuration file
settings_schema = Schema({
    "version": Regex(r"[0-9]+\.[0-9]+\.[0-9]+"),
    "annotator": str,
    Optional("filepath", default=None): str,
    Optional("save_path", default=None): str,
    Optional("session_path", default=None): str,
    "labels": [str],
    "dim_reductions": Schema({}, ignore_extra_keys=True),
    "backend": Schema({
        "name": str,
        "kwargs": object,
    }, error="Error in backend"),
    "widgets": [Schema({
        "name": str,
        "wtype": Or(
            WidgetType.WAVEFORM, WidgetType.SPECTROGRAM,
            WidgetType.SCATTER, WidgetType.AUDIO, WidgetType.VIDEO
        ),
        "position": Schema({
            "row": And(int, lambda n: n >= 0),
            "col": And(int, lambda n: n >= 0),
            Optional("rowspan", default=1): And(int, lambda n: n >= 0),
            Optional("colspan", default=1): And(int, lambda n: n >= 0)
        }),
        "kwargs": object
    })],
})


class UserSettings(QObject):
    '''
    Defines a presentation for user settings. Inherits from QObject, and thus
    can support asynchronous communication through signals
    '''

    def __init__(
            self, payload: Mapping[str, Any],
            parent: Union[QObject, None] = None
            ):
        '''
        Creates the user settings from the given data.

        Parameters
        ----------
        payload: Mapping[str, Any]
            The data used for the settings. This will be validated.
        parent: QObject | None
            The parent for this object. Default None.

        Raises
        ------
        SchemaError
            If the data doesn't pass the validation
        '''
        super().__init__(parent)
        # Validate the data.
        settings_schema.validate(payload)
        # Do the parsing only when the data is accessed
        self._data: Dict[str, Any] = payload

        # Do some post processing:
        # 1. Add the name of each component to their kwargs.
        # 2. If the widget is scatterwidget, add also labels to their kwargs
        # 2.1 Add the unlabeled to the possible labels
        if str(SampleState.UNLABELED) not in self._data["labels"]:
            labels = [str(SampleState.UNLABELED), *self._data["labels"]]
            self._data["labels"] = labels
        else:
            labels = self._data["labels"]

        self._process_widgets(labels)

    def __str__(self) -> str:
        return str(self._data)

    def __contains__(self, attr: str) -> bool:
        return attr in self._data

    def __setitem__(self, attr: str, value: Any):
        '''
        Convenience method for using Python indexing syntax

        Parameters
        ----------
        attr: str
            The attribute that should be set. Must be a string!
        value: Any
            The value to set for the attribute.
        '''
        self._data[attr] = value

    def __getattr__(self, attr: str) -> Any:
        '''
        Implementation for getattr, which allows dot based syntax
        (i.e. obj.attr).

        Parameters
        ----------
        attr: str
            The attribute to retrieve.
        '''
        if attr == "__name__":
            return self.__class__.__name__
        # Handle Python's special dunder methods
        if attr.startswith("__") and attr.endswith("__"):
            return self.__dict__[attr]

        if attr not in self._data:
            raise AttributeError(f"{self.__class__.__name__!r} doesn't have attribute "
                                 f"{attr!r}")
        return self._data[attr]

    def __getitem__(self, attr: str) -> Any:
        '''
        Support for accessing items using Python's indexing syntax.

        Parameters
        ----------
        attr: str
            The attribute to retrieve. NOTE: Must be a string, indexing by
            tuples is not supported.
        '''
        if isinstance(attr, tuple):
            raise TypeError(("Only string based lookup is supported! "
                            f"Got {attr!r}"))
        return self._data[attr]

    def get_total_amount_of_samples(self) -> int:
        '''
        Queries the total amount of samples present in the used dataset.
        NOTE: As this is not explicitly mentioned, the value is found out by
        "brute force". This might involve some I/O operations.

        Returns
        -------
        The total amount of samples used in the dataset.

        Raises
        ------
        RuntimeError
            If the amount of files could not be inferred from the dataset.
        '''
        # To find out the total amount of samples in the data, we must actually
        # look at the source files/directories, and, based on that, infer the
        # sample count.

        # First try to find components having source directories, as those
        # don't require any file reading.
        source_files_idx = []
        for i, widget in enumerate(self._data["widgets"]):
            kwargs: dict[str, Any] = widget.get("kwargs", {})

            # Check for source directories first
            if "source_dirs" in kwargs:
                sdirs = kwargs["source_dirs"]
                if len(sdirs) == 0:
                    continue
                fpath = pathlib.Path(sdirs[0])
                return sum(1 for f in fpath.iterdir() if f.is_file())

            # Collect indexes for widgets that might have file-based sources
            for key in ("source_path", "numpy_path", "id_mapping_numpy_file"):
                if key in kwargs:
                    source_files_idx.append((i, key))

        # If no component contains source directories, we check components
        # having source files. These really should be numpy arrays.
        for idx, key in source_files_idx:
            widget = self._data["widgets"][idx]
            kwargs = widget.get("kwargs", {})
            sfile = kwargs[key]
            if isinstance(sfile, list):
                sfile = sfile[0]

            fpath = pathlib.Path(sfile)
            if fpath.suffix != ".npy":
                continue

            data = io.load_numpy(fpath)
            return data.shape[0]

        raise RuntimeError("The total amount of samples could not be deduced")

    def to_dict(self, make_copy: bool = False) -> Dict[str, Any]:
        '''
        Converts the settings to a dict.

        Parameters
        ----------
        make_copy: bool, Optional
            If set to True, will make a deep copy of the settings. Otherwise
            a reference is returned. Default False.

        Returns
        -------
        Dict[str, Any]
            The settings as a dict
        '''
        return copy.deepcopy(self._data) if make_copy else self._data

    def serialize(self, session_dir: Path) -> Dict[str, Any]:
        '''
        Serializes the settings to a JSON/YAML format. Currently just
        returns the underlying data

        Parameters
        ----------
        session_dir: Path
            The path to the currently used session directory.

        Returns
        -------
        Dict[str, Any]
            The settings
        '''
        return copy.deepcopy(self._data)

    @classmethod
    def from_dict(
            cls, payload: Dict[str, Any], parent: Union[QObject, None]
            ) -> "UserSettings":
        '''
        Constructs the setting from a dict.

        Parameters
        ----------
        payload: Dict[str, Any]
            The data used to construct the settings. NOTE: Must pass the
            validation layer.
        parent: QObject | None
            The parent of the settings.

        Returns
        -------
        UserSettings
            The created settings object

        Raises
        ------
        SchemaError
            If the payload doesn't pass the validation
        '''
        return cls(payload, parent)

    @classmethod
    def from_yaml(
            cls, filepath: Path, parent: Union[QObject, None]
            ) -> "UserSettings":
        '''
        Constructs the settings from a YAML file.

        Parameters
        ----------
        filepath: Path
            The path to the YAML file.
        parent: QObject | None
            The parent of the created settings. Default None.

        Returns
        -------
        UserSettings
            The created settings

        Raises
        ------
        SchemaError
            If the contents of the file don't pass the validation
        '''
        payload = io.load_yaml(filepath)
        settings = cls(payload, parent)
        settings["filepath"] = str(filepath)
        return settings

    def _process_widgets(self, labels: List[str]):
        '''
        Does post-processing to widget information:
            1. Ensures that each widget has at least 'source_dirs',
            'source_path', or 'numpy_path' specified as kwargs
            2. Adds the name of widget to their own information.
            3. Adds the label information to the scatterwidgets.

        Parameters
        ----------
        labels: List[str]
            The set of labels to use in the application.

        '''
        for widget in self._data["widgets"]:
            name = widget["name"]
            wtype = widget["wtype"]
            kwargs = widget.get("kwargs", None)

            has_sources = kwargs is not None and ("source_dirs" in kwargs
                                                  or "numpy_path" in kwargs
                                                  or "source_paths" in kwargs
                                                  or "source_path" in kwargs)
            if not has_sources:
                raise RuntimeError((f"Widget {name!r} is missing "
                                    "'source_dirs', 'numpy_path', 'source_paths', or 'source_path' from "
                                    "'kwargs'"))
            # Check that the source directories actually have some files.
            if "source_dirs" in kwargs:
                dirpaths = kwargs.get("source_dirs")
                for dpath in dirpaths:
                    dpath = pathlib.Path(dpath)
                    if not dpath.exists() or not dpath.is_dir():
                        raise FileNotFoundError(("Source directory "
                                                 f"({str(dpath)!r}) for "
                                                 f"widget {name!r} does not "
                                                 "point to a valid directory"))
                    if sum(1 for f in dpath.iterdir() if f.is_file()) < 1:
                        raise RuntimeError(("Source directory "
                                            f"({str(dpath)!r}) for widget "
                                            f"{name!r} does not contain any files"))

            kwargs["name"] = name
            if wtype == WidgetType.SCATTER:
                kwargs["labels"] = labels
