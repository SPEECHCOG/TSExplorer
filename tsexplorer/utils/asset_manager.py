''' This file defines a simple asset manager that handles loading and selecting
suitable data for the widgets '''

from . import logger
from ..metadata import SampleID, Path, WidgetType, SQLException
from . import io
from .. import database
from .buffer import Buffer

import numpy as np
import pathlib
import warnings
from typing import List, Dict, Mapping, Callable, Any

LoaderFn = Callable[[Path], Any]


class AssetManager:
    """
    This defines a simple asset manager, whose responsibility is to load
    and store data to be displayed. Handles all the complexities related to
    loading different types of data from different directories and file
    structures.
    """

    # The filetypes we know, and can load
    _KNOWN_FILETYPES: Dict[str, LoaderFn] = {
            ".npy": io.load_numpy,
            ".wav": io.load_wav,
    }

    def __init__(
            self, dp_path: Path, table_name: str,
            widget_config: List[Dict[str, Any]], capacity: int = 10
            ):
        '''
        Creates a new asset-manager

        Parameters
        ----------
        dp_path: Path
            Full path to the database.
        table_name: str
            The name of the table, where the annotations are stored in the db.
        widget_config: List[Dict[str, Any]]
            The configuration for the widgets.
        capacity: int
            The capacity used for the internal buffer.
        '''
        self._logger = logger.get_logger("AssetManager")
        self._buffer = Buffer(capacity)

        # Open connection to the database
        self._db_path: str = str(dp_path)
        self._conn = database.create_connection(str(dp_path), "asset-manager")
        self._table_name: str = table_name

        self._loaders: Dict[str, LoaderFn] = self._determine_loaders(
                widget_config
        )
        self._sources: Dict[str, List[str]] = self._extract_sources(
                widget_config
        )

        self._widget_config: List[Dict[str, Any]] = widget_config

    def get_sample(
            self, widget_name: str, widget_type: WidgetType,
            sample_id: SampleID
            ) -> Dict[str, Any]:
        '''
        Retrieves the given sample for the given widget.

        Parameters
        ----------
        widget_name: str
            The name of the widget
        widget_type: WidgetType
            The type of the widget.
        sample_id: SampleID
            The id of the sample to retrieve

        Returns
        -------
        Dict[str, Any]
            Dict containing (label, data) key-value pairs. Currently the
            directory/filename is used as label.

        Raises
        ------
        RuntimeError
            If the widget is unknown
        '''
        if widget_name not in self._sources:
            # Unknown widget, really cannot know what to do here
            self._logger.error(f"Unknown widget: {widget_name!r}")
            raise RuntimeError(f"Unknown widget: {widget_name!r}!")

        self._logger.debug(f"Querying sample for {widget_type}")
        
        # Some special cases: If widget is audio, we just return the file path or the index (the latter if we use Numpy matrices)
        if widget_type == WidgetType.AUDIO:
            try:
                label, files = next(iter(self._sources[widget_name].items()))
                return {label: files[sample_id]}
            except:
                return {sample_id: sample_id}

        # In case of video, we must additionally determine the start and end
        # points for the video. This requires querying the database for the
        # order number.
        if widget_type == WidgetType.VIDEO:
            return self._query_video(widget_name, sample_id)

        # waveform can take in either a single source file of shape
        # (n-signals, n-channels, n-samples) or directory of wav-files
        if widget_type == WidgetType.WAVEFORM:
            return self._query_waveform(widget_name, sample_id)
        return self._query(widget_name, sample_id)
        # Otherwise, we check if the sample is already in the buffer
        # if (sample_id, widget_name) in self._buffer:
        #     return self._buffer[sample_id, widget_name]

        # # If it is not, we need to retrieve it from the sources
        # source_dirs = self._sources[widget_name]
        # data = {}
        # for dirname, dir_files in source_dirs.items():
        #     fp = dir_files[sample_id]
        #     payload = self._loaders[widget_name](fp)
        #     data[dirname] = payload
        # self._buffer.append(sample_id, widget_name, data)
        # return data

    def shutdown(self):
        '''
        Should be called before the item is destroyed to make sure that the
        connection to database is closed.
        '''
        self._conn.close()
        self._conn = None

    def clear_buffer(self):
        '''
        Resets the internal buffer of the asset manager, but does not wipe the
        determined loaders.
        '''
        self._buffer.clear()

    def serialize(self) -> Mapping[str, Any]:
        '''
        Serialize the state of the asset manager to the disk.

        Returns
        -------
        Mapping[str, Any]
            A JSON/YAML compatible presentation of the manager's state.
        '''
        out = {}
        out["db_path"] = self._db_path
        out["table_name"] = self._table_name
        return out

    def deserialize(
            self, payload: Mapping[str, Any],
            widget_config: List[Dict[str, Any]]
            ):
        '''
        Restore managers previously saved state.

        Parameters
        ----------
        payload: Mapping[str, Any]
            The deserialized state to restore.
        widget_config: List[Dict[str, Any]]
            The deserialized widget configuration.
        '''
        # Close the old connection
        if self._conn.isOpen():
            self._conn.close()
        database.remove_connection(self._conn)

        # Open connection to the new/previous database
        self._db_path = payload["db_path"]
        self._table_name = payload["table_name"]
        self._conn = database.create_connection(self._db_path, "asset-manager")

        self.reload(widget_config)

    def reload(self, widget_config: List[Dict[str, Any]]):
        '''
        Reloads the loaders and sources based on the given configuration.

        Parameters
        ----------
        widget_config: List[Dict[str, Any]]
            The updated widget configuration
        '''
        self._loaders = self._determine_loaders(widget_config)
        self._sources = self._extract_sources(widget_config)
        self._buffer.clear()

    def _query(self, widget_name, sample_id: SampleID):
        if (sample_id, widget_name) in self._buffer:
            return self._buffer[sample_id, widget_name]

        # If it is not, we need to retrieve it from the sources
        source_dirs = self._sources[widget_name]
        data = {}
        for dirname, dir_files in source_dirs.items():
            fp = dir_files[sample_id]
            payload = self._loaders[widget_name](fp)
            data[dirname] = payload
        self._buffer.append(sample_id, widget_name, data)
        return data

    def _query_video(
            self, widget_name: str, sample_id: SampleID
            ) -> Dict[str, int]:
        '''
        Queries the next segment of a video that should be played.

        Parameters
        ----------
        widget_name: str
            The name of the widget.
        sample_id: SampleID
            The sample to which the video clip should correspond to

        Returns
        -------
        Dict[str, int]
            Returns the order number of the video clip for the given file-path
        '''
        self._logger.debug(f"Query order number for sample {sample_id}")
        # Query the order number from the database
        try:
            results = database.query(
                self._conn,
                (f"SELECT sid, ordernumber FROM {self._table_name} "
                 f"WHERE sid = {int(sample_id)}"),
                columns=["sid", "ordernumber"]
                )
        except SQLException as e:
            self._logger.error(f"Error while querying database: {str(e)}")
            raise
        else:
            # There should always be just one result:
            if len(results) != 1:
                self._logger.error(("Expected exactly one match from the "
                                    f"query, but got {len(results)}"))
                raise RuntimeError(("Error while querying the database: "
                                    "Expected exactly one match, but got "
                                    f"{len(results)}"))

            # NOTE: In this case the sample-id corresponds to the order of
            # the clips
            sample_id = results[0].sid
            fpath = self._sources[widget_name]
            return {str(fpath): sample_id}

    def _query_waveform(
            self, widget_name: str, sample_id: SampleID
            ) -> None:

        # Three cases:
        # 1) a directory of WAV files
        # 2) a single Numpy file with shape (n_samples, n_channels, time)
        # 3) a Numpy object array where each sample can have a different length

        source = self._sources[widget_name]

        # Case 1: -> Use the "standard" method for loading data
        if not isinstance(source, str):
            return self._query(widget_name, sample_id)
        
        # Load the array from the source
        arr = self._loaders[widget_name](source)

        # Case 2: -> Regular 3D array
        if arr.ndim == 3:
            if arr.shape[0] <= sample_id:
                raise RuntimeError(
                    f"{widget_name!r}: Expected a (n_samples, n_channels, time) shaped array "
                    f"but got array with shape {arr.shape}"
                )
            return {str(source): arr[sample_id, ...]}
        
        # Case 3: -> Object array with variable-length samples
        if isinstance(arr, np.ndarray) and arr.dtype == object:
            if len(arr) <= sample_id:
                raise RuntimeError(
                    f"{widget_name!r}: Object array too short for sample_id {sample_id}"
                )
            sample = arr[sample_id]
            if not isinstance(sample, np.ndarray):
                raise RuntimeError(
                    f"{widget_name!r}: Expected each object array element to be a NumPy array, "
                    f"but got {type(sample)}"
                )
            return {str(source): sample}

        # Unknown format
        if widget_name != "label_box":
            raise RuntimeError(f"{widget_name!r}: Unsupported array format with shape {arr.shape} and dtype {arr.dtype}")

    def _extract_sources(
            self, widget_config: List[Dict[str, Any]]
            ) -> Dict[str, List[str]]:
        '''
        Extract the source files for each widget. NOTE: Parses only widgets
        that have directories.

        Parameters
        ----------
        widget_config: List[Dict[str, Any]]
            The configuration for the widgets

        Returns
        -------
        Dict[str, List[str]]
            The source file(s) for each widget
        '''
        sources = {}
        for widget in widget_config:
            wname = widget.get("name")
            kwargs = widget.get("kwargs")
            if "source_path" in kwargs:
                sources[wname] = kwargs.get("source_path")
            elif "source_dirs" in kwargs:
                tmp = {}
                for dirpath in kwargs.get("source_dirs"):
                    files = sorted(
                            f for f in pathlib.Path(dirpath).iterdir()
                            if f.is_file()
                        )
                    tmp[dirpath] = files
                    sources[wname] = tmp
            elif "numpy_path" in kwargs:
                sources[wname] = kwargs.get("numpy_path")
            elif "source_paths" in kwargs:
                sources[wname] = kwargs.get("source_paths")
        return sources

    def _determine_loaders(
            self, widget_config: List[Dict[str, Any]]
            ) -> Dict[str, LoaderFn]:
        '''
        Determine the data loaders for each widget. This will be done based on
        two indicators:
            1. The type of the data we are loading
            2. The type of the widget that is asking for the data.
        Parameters
        ----------
        widget_config: List[Dict[str, Any]]
            The sources for the widgets
        '''
        out = {}

        for widget in widget_config:
            wname = widget.get("name")
            wtype = widget.get("wtype")
            kwargs = widget.get("kwargs")
            if "source_dirs" in kwargs:
                source_dirs = kwargs.get("source_dirs")
                dpath = pathlib.Path(source_dirs[0])
                sample_path = next(dpath.iterdir())
            elif "source_path" in kwargs:
                source = kwargs.get("source_path")
                sample_path = pathlib.Path(source)
            elif "source_paths" in kwargs:
                source = kwargs.get("source_paths")
                sample_path = pathlib.Path(source[0])

            # Audio and video are special cases, as they take in the filepaths,
            # and handle the loading by themselves
            if wtype == WidgetType.AUDIO or wtype == WidgetType.VIDEO:
                continue

            # Otherwise, we just check for the suffix of our sample, and
            # determine the loader based on that.
            if sample_path.suffix not in self._KNOWN_FILETYPES:
                warn_msg = ("Cannot load unknown filetype "
                            f"{sample_path.suffix!r}! Using the filepath as "
                            "a backup value")
                self._logger.warning(warn_msg)
                warnings.warn(warn_msg)

                out[wname] = lambda fp: pathlib.Path(fp)
            else:
                out[wname] = self._KNOWN_FILETYPES[sample_path.suffix]
        return out
