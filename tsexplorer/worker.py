'''
This module defines a generic worker class that can be used to move a job
to an another thread
'''

import os

from .utils import logger, io
from .utils.misc import deprecated
from .dim_reduction import IDimReduction
from .user_settings import UserSettings
from .metadata import WidgetType

from typing import Callable, Tuple, Mapping, Any, Optional

from PySide6.QtCore import QObject, Slot, Signal


class GuiWorker(QObject):
    '''
    Defines a purpose-built Worker object used to apply dimensionality
    reductions, and reload previous sessions:

    sign_task_success: object
        Signal emitted when the dimensionality reduction task has completed.
    sign_reload_success: Mapping[str, Any]
        Emitted when the 'load_state' task succeeds.
    sign_task_failure: str
        Emitted when ANY task fails. Contains stringified version of the error
    sign_finished
        Emitted when the worker finishes. Currently unused. Emitted when ANY
        task fails. Contains stringified version of the error.

    '''
    sign_task_success = Signal(object, name="sign_success")
    sign_reload_success = Signal(object, name="sign_reload_success")
    sign_task_failure = Signal(str, name="sign_failure")
    sign_finished = Signal(name="sign_finished")

    def __init__(self, parent: Optional[QObject] = None):
        '''
        Creates new worker.

        Parameters
        parent: Optional[QObject]
            The parent of the worker. Note that by setting the parent, the
            place where the constructor and destructor of the worker are run
            might change. Default None.
        '''
        super().__init__(parent)
        self._logger = logger.get_logger("GuiWorker", log_to_file=False)

    @Slot(object, str, str, object)
    def apply_dim_reduction(
            self, algo_klass: IDimReduction, wname: str, fpath: str,
            kwargs: Mapping[str, Any]
            ):
        '''
        Applies dimensionality reduction to a given data.

        Parameters
        ----------
        algo_klass: IDimReduction
            The dimensionality reduction algorithm to use.
        wname: str
            The name of the widget where the data is applied to.
        fpath: str
            The path to the data.
        **kwargs: Mapping[str, Any]
            Any possible keyword arguments passed to the algorithm

        Emits
        -----
        sign_task_success
            If the task completes successfully.
        sign_task_failure
            If the computation fails.
        '''
        try:
            self._logger.debug("Applying dimensionality reduction")

            # Determine algorithm name for file naming
            algo_name = algo_klass.__name__.lower()
            reduced_path = f"{os.path.splitext(fpath)[0]}_dim_reduced_{algo_name}.npy"

            # Try to load precomputed reduced features
            if os.path.exists(reduced_path):
                self._logger.debug(f"Loading precomputed reduced features from {reduced_path}")
                results = io.load_numpy(reduced_path)
            else:
                feats = io.load_numpy(fpath)
                inst = algo_klass(**kwargs)
                results = inst.fit_transform(feats)
                io.save_numpy(reduced_path, results)
                self._logger.debug(f"Saved reduced features to {reduced_path}")

            self.sign_task_success.emit((wname, results))
        except Exception as e:
            self._logger.debug(f"Dim reduction failed: {str(e)}")
            self.sign_task_failure.emit(str(e))

    @Slot(str)
    def load_state(self, filepath: str):
        state = io.load_yaml(filepath)

        # --- User configuration ---
        cfg = state.pop("settings", None)
        if cfg is None:
            self.sign_task_failure.emit("Missing deserialized user settings")

        # Create temporary object for the life time of this function
        settings = UserSettings(cfg, None)

        # ---- Load backend ----
        backend = state.pop("backend", None)
        if backend is None:
            self.sign_task_failure.emit("Missing deserialized backend!")

        # Load possible files for the backend.
        src = backend.get("source_file", None)
        if src is not None:
            backend["features"] = io.load_numpy(src)

        src_points = backend.get("const_points", None)
        if src_points is not None:
            backend["const_points"] = io.load_numpy(src_points)

        src_user_points = backend.get("queued_points", None)
        if src_user_points is not None:
            backend["queued_points"] = io.load_numpy(src_user_points)

        cluster_ids = backend.get("cluster_ids", None)
        if cluster_ids is not None:
            # This can be an object array, so allow_pickle must be set.
            backend["cluster_ids"] = io.load_numpy(
                    cluster_ids, allow_pickle=True
            )

        # Specific to FFT backend -->
        src_medoids = backend.get("medoids", None)
        if src_medoids is not None:
            backend["medoids"] = io.load_numpy(src_medoids)

        # ------- Annotation widget --------
        annotation_w = state.pop("annotation_widget", None)
        if annotation_w is None:
            self.sign_task_failure.emit(
                    "Missing deserialized annotation widget!"
            )

        # Reload data for possible scatter widgets
        for widget in settings.widgets:
            name = widget["name"]
            wtype = widget["wtype"]
            if wtype != WidgetType.SCATTER:
                continue

            point_path = annotation_w[name]["points"]
            annotation_w[name]["points"] = io.load_numpy(point_path)

        # ---------- Controller ------------
        controller = state.pop("controller", None)
        if controller is None:
            self.sign_task_failure.emit("Missing deserialized controller!")

        out = {
                "settings": cfg, "backend": backend,
                "controller": controller, "annotation_widget": annotation_w
        }
        self.sign_reload_success.emit(out)


# DEPRECATED
@deprecated("Old-API, use 'GuiWorker' instead")
class Worker(QObject):
    '''
    Defines a generic worker that can be used to run any job on another thread.

    Signals
    -------
    finished: int
        Signal that is sent when the worker finishes, regardless of whether the
        operation was successful or not
    success: object
        The signal emitted if the operation was successful. Emits the results
        of the operation, which can be any Python object
    failure: str
        The signal emitted if the operation fails. The emission will contain a
        stringified version of the happened error
    '''
    finished = Signal(int, name="finished")
    success = Signal(object, name="success")
    failure = Signal(str, name="failure")

    def __init__(
            self, fn: Callable, *args: Tuple[Any, ...],
            **kwargs: Mapping[str, Any]
            ):
        '''
        Creates a worker for the specified operation

        Parameters
        ----------
        fn: Callable
            The function that will be executed during the 'run' function of
            this worker
        *args: Tuple[Any, ...]
            Any possible arguments that will be passed to the function
        **kwargs: Mapping[str, Any]
            Any possible named arguments that will be passed to the function
        '''
        super().__init__()
        self._fn = fn
        self._args = args
        self._kwargs = kwargs

    def set_args(self, *args, **kwargs):
        self._args = args
        self._kwargs = kwargs

    @Slot()
    def run(self):
        '''
        Runs the function with the given parameters, and emits the results
        '''
        try:
            res = self._fn(*self._args, **self._kwargs)
            self.success.emit(res)
        except Exception as e:
            self.failure.emit(str(e))
        finally:
            self.finished.emit(1)
