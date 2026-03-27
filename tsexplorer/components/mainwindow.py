'''This file defines the Main window abstraction class for all windows that
are used in an application. The window consists of central widget and menu bars
'''

from ..metadata import Path, SQLException
from .. import dim_reduction
from ..controller import Controller
from ..user_settings import UserSettings
from ..utils import io, logger
from ..utils.misc import get_user_data_directory, prettify_map
from ..backend import load_selector, ISelector
from ..worker import GuiWorker
from .annotationwidget import AnnotationWidget

import pathlib
from typing import Optional, Dict, Any, Tuple, Mapping
import copy
import time
import uuid  # For generating unique dir/filenames
import sys
import traceback

from schema import SchemaError
from PySide6.QtWidgets import (
        QMainWindow, QMenu, QFileDialog, QMessageBox,
        QProgressDialog
)
from PySide6.QtGui import QAction
from PySide6.QtCore import Qt, QObject, Slot, Signal, QThread, QTimer, QEvent

_SECOND: int = 1000
_VALID_MSG_BOXES: Tuple[str] = ("information", "warning", "critical")
_MAX_WAIT: int = 0.5*_SECOND


class Window(QMainWindow):
    '''
    Defines the main window of the application. Acts mostly as a wrapper
    for the other components. Additionally takes care of some of the signal
    handling.

    Signals
    -------
    sign_request_dim_reduction: object, str, str, object
        Emitted when a dimensionality reduction is required. Contains the
        class used for the reduction, name of the requesting widget, filepath
        and any possible keyword arguments for the algorithm

    sign_request_state_load: str
        Emitted a previous session needs to be loaded. Contains the path to the
        file containing the serialized session.

    sign_dim_reduction_ready: object
        Emitted when the requested dimensionality reduction is ready.

    sign_reload:
        Emitted when the configuration is reloaded
    '''

    sign_request_dim_reduction = Signal(
            object, str, str, object, name="sign_request_dim_reduction"
    )
    sign_request_state_load = Signal(
            str, name="sign_request_state_load"
    )
    sign_dim_reduction_ready = Signal(
            object, name="sign_dim_reduction_ready"
    )
    sign_dim_reduction_cancelled = Signal(name="sign_dim_reduction_cancelled")

    sign_reload = Signal(name="sign_reload")

    def __init__(self, config_path: str, parent: Optional[QObject] = None):
        '''
        The constructor for the main window. In most cases, should not have a
        parent widget

        Parameters
        ----------
        parent: Optional[QObject]
            The parent object of this window. Default None
        '''

        super().__init__(parent)
        start = time.perf_counter()

        self.setWindowTitle("TSExplorer")
        self.resize(800, 600)

        # Indicate if the initialization was successful
        self._init_success: bool = True
        thread_created: bool = False
        self._logger = logger.get_logger("mainwindow")
        self._logger.info("Starting to initialize mainwindow")

        self._dialog: QProgressDialog = None
        self._current_progress: Optional[int] = None
        self._is_ready: bool = False

        try:

            # =========== Load settings && open connection to db ========
            self._settings: UserSettings = self._load_settings(config_path)
            n_samples = self._settings.get_total_amount_of_samples()
            self._logger.debug(f"Dataset contains {n_samples} samples in total")
            # Create unique path for the session.
            session_path = get_user_data_directory(
                    ["tsexplorer", f"{uuid.uuid4().hex}"]
            )

            if session_path.exists() or session_path.is_dir():
                raise FileExistsError(("Could not create unique directory: "
                                      f"{str(session_path)!r} already exists!"))

            # Create the data-directory
            session_path.mkdir(parents=True)

            # Store the datapath in the settings.
            self._settings["session_path"] = str(session_path)

            self._controller = Controller(session_path, n_samples, parent=self)
            self._logger.info("Created controller")

            # ===== Widgets ======
            # NOTE: AnnotationWidget must be created after controller to ensure
            # that the database is created.
            self._annotation_widget = AnnotationWidget(
                    dp_path=self._controller.db_path,
                    table_name=self._controller.default_table,
                    n_samples=n_samples, parent=self
            )
            self._logger.info("Created annotation widget")
            self.setCentralWidget(self._annotation_widget)

            # ===== Backend =======
            self._backend = self._create_backend(
                    self._settings.backend.get("name")
            )

            # ===== Menubar & Actions =====
            self._create_menubar_and_actions()

            # ==== Connect signals and slots ====
            self._connect_signals_and_slots()

            self._annotation_widget.setVisible(True)

            # ===== Worker thread ======
            # Initialize the thread, and the worker. Note that the same worker
            # will be used to process all tasks
            self._thread = QThread()
            thread_created = True
            self._worker = GuiWorker()
            self._worker.moveToThread(self._thread)

            # Connect all the necessary signals for the worker
            self._worker.sign_task_success.connect(
                    self.sign_dim_reduction_ready
            )
            self._worker.sign_reload_success.connect(
                    self._restore
            )

            self._worker.sign_task_failure.connect(self._show_dialog)
            self._thread.finished.connect(self._worker.deleteLater)

            self.sign_request_dim_reduction.connect(
                    self._worker.apply_dim_reduction,
                    Qt.QueuedConnection
            )
            self.sign_request_state_load.connect(
                    self._worker.load_state,
                    Qt.QueuedConnection
            )

            # Start the thread
            self._logger.debug("Starting worker thread")
            self._thread.start()

            # Request the first sample
            self._controller.on_request_sample(0)

            # Check if dimensionality reduction is required, and request it if
            # needed
            self._annotation_widget.maybe_require_dim_reduction()
            stop = time.perf_counter()
            self._logger.debug(f"Start time took: {stop-start:.3f}s")

        except SchemaError as e:
            etype, e_msg, exc_traceback = sys.exc_info()
            einfo = "\n".join(traceback.format_exc(limit=10).splitlines())
            self._logger.debug(f"{etype}: {str(e_msg)}, trace: {einfo}")

            _ = QMessageBox.critical(
                    self, "TSExplorer", f"Error in config: {str(e)}"
            )
            self._init_success = False
        except FileNotFoundError as e:
            etype, e_msg, exc_traceback = sys.exc_info()
            einfo = "\n".join(traceback.format_exc(limit=10).splitlines())
            self._logger.debug(f"{etype}: {str(e_msg)}, trace: {einfo}")

            _ = QMessageBox.critical(
                    self, "TSExplorer", f"Could not find file!: {str(e)}"
            )
            self._init_success = False
        except SQLException as e:
            etype, e_msg, exc_traceback = sys.exc_info()
            einfo = "\n".join(traceback.format_exc(limit=10).splitlines())
            self._logger.debug(f"{etype}: {str(e_msg)}, trace: {einfo}")

            _ = QMessageBox.critical(
                    self, "TSExplorer", f"Error with database: {str(e)}"
            )

        except Exception as e:
            etype, e_msg, exc_traceback = sys.exc_info()
            einfo = "\n".join(traceback.format_exc(limit=10).splitlines())
            self._logger.debug(f"{etype}: {str(e_msg)}, trace: {str(einfo)}")

            _ = QMessageBox.critical(self, "TSExplorer", f"Error: {str(e)}")
            self._init_success = False

        finally:
            # Ensure that the thread is killed in case of failure
            if not self._init_success and thread_created:
                self._quit_thread()
            self._logger.info("mainwindow constructor finished")

            # Open the dialog if the widgets are not ready yet
            QTimer.singleShot(0, self._on_open_dialog)

    @property
    def init_success(self) -> bool:
        '''
        Shows if the initialization of the application was successful or not.
        Should be checked after the constructor has run to see if the
        event-loop should be started
        '''
        return self._init_success

    @property
    def settings(self) -> UserSettings:
        ''' Getter for the current settings'''
        return self._settings

    def closeEvent(self, event: QEvent):
        '''
        Overrides the closeEvent to check that the user is not accidentally
        dismissing already labeled files.

        Parameters
        ----------
        event: QEvent
            The event to check
        '''
        # First, test if the user really wants to close the application. Only
        # after that close the connection and save the session
        was_annotated = self._controller.was_annotated()
        self._logger.debug((f"Annotations done?: {was_annotated}, controller"
                            f" updated: {self._controller.was_updated}"))
        remove_current_sess = False

        if not was_annotated:
            maybe_quit = QMessageBox.question(
                    self, "TSExplorer", ("Do you really want to quit from the "
                                        "application?")
            )
            # Abort the shutdown here if the user clicked 'x' or 'no' buttons
            if maybe_quit != QMessageBox.StandardButton.Yes:
                event.ignore()
                return

            remove_current_sess = "save_path" not in self._settings
            # Otherwise, go to shutdown
            self._shutdown(event, remove_current_sess)

        # If no progress has been made after the last update, we can just ask
        # The user if they want to quit, and close application WITHOUT removing
        # the current sessions
        elif not self._controller.was_updated:
            maybe_quit = QMessageBox.question(
                    self, "TSExplorer", ("Do you really want to quit from the "
                                        "application?")
            )
            # Abort the shutdown here if the user clicked 'x' or 'no' buttons
            if maybe_quit != QMessageBox.StandardButton.Yes:
                event.ignore()
                return

            remove_current_sess = "save_path" not in self._settings
            # Otherwise, go to shutdown
            self._shutdown(event, remove_current_sess)
        # Otherwise, user is asked if they would like to save the progress
        else:
            msg_box = QMessageBox(self)
            msg_box.setWindowTitle("TSExplorer")
            msg_box.setText("Do you want to save the progress?")

            save_btn = msg_box.addButton(
                    r"Save and quit", QMessageBox.ButtonRole.AcceptRole
            )
            quit_btn = msg_box.addButton(
                    "Quit without saving",
                    QMessageBox.ButtonRole.DestructiveRole
            )
            cancel_btn = msg_box.addButton(
                    "Cancel", QMessageBox.ButtonRole.RejectRole
            )
            msg_box.exec()

            if msg_box.clickedButton() == cancel_btn:
                event.ignore()
                return

            elif msg_box.clickedButton() == save_btn:
                self._save_sess_as()
                remove_current_sess = False
                # Reset the state
                self._controller.was_updated = False

            elif msg_box.clickedButton() == quit_btn:
                remove_current_sess = "save_path" not in self._settings

            self._shutdown(event, remove_current_sess)

    def _create_menubar_and_actions(self) -> None:
        '''Creates the menubar for the application'''

        save_action = QAction("&Save session", self)
        save_action.setShortcut("Ctrl+S")
        save_action.triggered.connect(self._save_sess)

        save_as_action = QAction("Save as", self)
        save_as_action.setShortcut("Ctrl+Shift+S")
        save_as_action.triggered.connect(self._save_sess_as)

        reload_action = QAction("&Reload config", self)
        reload_action.setShortcut("F5")
        reload_action.triggered.connect(self._reload_config)

        load_action = QAction("Load previous session", self)
        load_action.setShortcut("Ctrl+O")
        load_action.triggered.connect(self._load_sess)

        export_action = QAction("Export annotations as .csv", self)
        export_action.triggered.connect(self._export_annotations)

        remove_session_action = QAction("Remove a specific session save", self)
        remove_session_action.triggered.connect(self._remove_session)

        clear_action = QAction("Clear all sessions (except current)", self)
        clear_action.triggered.connect(self._clear_sessions)

        # ---- Menu bar ----
        mbar = self.menuBar()  # Use the build-in menubar

        # File menu
        file_menu = QMenu("&file", self)

        file_menu.addAction(save_action)
        file_menu.addAction(save_as_action)
        mbar.addMenu(file_menu)

        # Session menu
        session_menu = QMenu("&session")
        session_menu.addAction(reload_action)
        session_menu.addAction(load_action)
        session_menu.addAction(export_action)
        session_menu.addAction(remove_session_action)
        session_menu.addAction(clear_action)
        mbar.addMenu(session_menu)

    def _connect_signals_and_slots(self):
        ''' Connects signals and slots'''
        # =========== MainWindow =============
        self._controller.sign_last_sample.connect(self._on_last_sample)

        # =========== AnnotationWidget ==============

        # Update the state of a sample in the database
        # (User changed label from box)
        self._annotation_widget.sign_sample_state_changed.connect(
                self._controller.on_sample_state_change
        )

        # The user requested a new sample
        self._annotation_widget.sign_request_sample.connect(
                self._controller.on_request_sample
        )

        # Return the user requested new sample by pressing "next-btn"
        self._controller.sign_return_sample.connect(
                self._annotation_widget.set_sample
        )

        self._controller.sign_last_sample.connect(
                self._annotation_widget.on_last_sample
        )

        # =========== ScatterWidget ============
        # Retrieve all scatter widgets
        scatter_widgets = self._annotation_widget.get_scatter_widgets()

        # Connect changes in database to the scatter_widgets

        for widget in scatter_widgets.values():
            self._controller.sign_sample_state_changed.connect(
                    widget.on_sample_state_change
            )
            widget.sign_user_selected_sample.connect(
                    self._controller.on_user_selected_sample
            )
            widget.sign_user_set_sample.connect(
                    self._controller.on_user_set_sample
            )
            widget.sign_ready.connect(
                    self._controller.on_sync_state
            )

            self._controller.sign_state.connect(
                    widget.on_state_update
            )

        # Request dimensionality reduction
        self._annotation_widget.sign_request_dim_reduction.connect(
                self._apply_dim_reduction
        )

        # Return the results of the dimensionality reduction
        self.sign_dim_reduction_ready.connect(
                self._annotation_widget.after_dim_reduction,
                Qt.QueuedConnection
        )
        self.sign_dim_reduction_cancelled.connect(
                self._annotation_widget.dim_reduction_cancelled
        )
        # Connect errors
        self._annotation_widget.sign_error.connect(self._show_dialog)
        self._controller.sign_error.connect(self._show_dialog)

        # Update the progress dialog
        self._annotation_widget.sign_progress_update.connect(
                self._on_progress_update
        )
        self._annotation_widget.sign_widget_ready.connect(self._on_ready)
        # ========= Backend ==============

        # Controller --> backend
        self._controller.sign_sample_state_changed.connect(
                self._backend.on_sample_state_change
        )

        self._controller.sign_request_sample.connect(
                self._backend.select_sample
        )

        # Backend --> Controller
        self._backend.sign_sample_selected.connect(
                self._controller.on_new_sample
        )
        self._backend.sign_sample_updated.connect(
                self._controller.on_update_sample
        )

    def _create_backend(self, name: str) -> ISelector:
        '''
        Tries to construct the configured backend.

        Parameters
        ----------
        name: str
            The name of the selector to load.

        Returns
        -------
        ISelector
            The constructed backend.

        Raises
        ------
        ValueError
            If the configuration doesn't contain a feature file
        '''
        return load_selector(
                name, parent=self, **self._settings.backend.get("kwargs")
        )

    def _shutdown(self, event: QEvent, remove_current_sess: bool):
        '''
        Shutdown the application

        Parameters
        ----------
        event: QEvent
            The Qt's automatically created close event
        remove_current_sess: bool
            If set to True, the current session save will be removed
        '''
        self._controller.close_session()
        if remove_current_sess:
            self._logger.debug("Removing session")
            io.rm_dir(self._settings.session_path)

        # Inform all other widgets that the application is quitting.
        self._annotation_widget.shutdown()

        # Finally, quit the worker thread, and propagate rest of time
        # work to the Qt's default closeEvent handler
        self._quit_thread()
        self._logger.debug("Shutdown main window")
        QMainWindow.closeEvent(self, event)

    def _quit_thread(self, wait_for: int = _MAX_WAIT):
        '''
        Tries to quit the current thread nicely. Posts a 'quit' event on the
        threads queue, and waits for 'wait' ms. If the thread is still running
        after the wait, terminates it immediately.

        Parameters
        ----------
        wait_for: int
            The time (in ms) to wait for the thread to process the 'quit'
            event. Default _MAX_WAIT
        '''
        self._thread.quit()
        self._thread.wait(wait_for)
        if self._thread.isRunning():
            self._thread.terminate()

    @Slot(str, str, str, object)
    def _apply_dim_reduction(
            self, wname: str, fpath: Path, algo_name: str,
            kwargs: Mapping[str, Any]
            ):
        '''
        Apply's dimensionality reduction to a given data.
        A 'sign_dim_reduction_ready' signal is emitted when the dimensionality
        reduction is completed.

        Parameters
        ----------
        wname: str
            The name of the created widget.
        fpath: Path
            The path to the data to which the dimensionality reduction is
            applied to.
        '''

        # Remove the possible "default" key from the kwargs, as it is not
        # an accepted keyword for any of the algorithms.
        kwargs = copy.deepcopy(kwargs)
        kwargs.pop("default", None)

        self._logger.debug(f"Using {algo_name!r} for dim reduction: {kwargs}")
        algo_klass = dim_reduction.get_dim_reduction(algo_name)
        self.sign_request_dim_reduction.emit(algo_klass, wname, fpath, kwargs)

        # If the widget is already finished, this must be a change in the
        # used dimensionality reduction tool, so create a new dialog
        if self._is_ready:
            self._dialog = QProgressDialog(
                    "Calculating ...", "Cancel", 0, 100, parent=self
            )
            self._dialog.canceled.connect(self.sign_dim_reduction_cancelled)
            self.sign_dim_reduction_ready.connect(self._dialog.cancel)
            self._dialog.exec()

    def _load_settings(self, config_path: str) -> UserSettings:
        '''
        Loads the user configuration.

        Parameters
        ----------
        config_path: str
            Path to the user configuration

        Returns
        -------
        UserSettings
            The loaded and validated settings
        '''

        fpath = pathlib.Path(config_path).resolve()
        return UserSettings.from_yaml(fpath, self)

    def _save_sess_impl(self, filepath: Path) -> bool:
        '''
        Tries to save the current session to the given filepath.

        Parameters
        ----------
        filepath: Path
            Path to the file where the session is stored. Should be a .yaml
            file

        Returns
        -------
        bool:
            True if the saving succeeded, False otherwise
        '''
        # Serialize everything to YAML. However, try, to keep everything
        # TOML compliant

        # We give each component a "context", which is just path to the
        # currently used save-directory.
        session_path = self._settings.session_path
        payload: Dict[str, Any] = {}
        payload["settings"] = self._settings.serialize(session_path)
        # Add the save path to the serialized payload, but not the actual
        # settings yet, as we don't know if the saving will succeed.
        payload["settings"]["save_path"] = str(filepath)

        payload["annotation_widget"] = self._annotation_widget.serialize(
                session_path
        )
        payload["backend"] = self._backend.serialize(session_path)
        payload["controller"] = self._controller.serialize(session_path)
        try:
            io.dump_yaml(filepath, payload)
            self._set_status_msg("Saved session successfully")
            self._controller.was_updated = False
            return True
        except Exception as e:
            self._show_dialog(
                    f"Error while saving the session {str(e)}", "warning"
            )
            return False

    # ------- Slots ------>

    @Slot()
    def _restore(self, session: Dict[str, Any]):
        '''
        Restores previously saved session.

        Parameters
        ----------
        session: Dict[str, Any]
            The mapping containing all the information related to the loaded
            session. Should contain the following keys:
                - 'settings'
                - 'backend'
                - 'controller'
                - 'annotation_widget'
        '''
        self._settings = UserSettings(session["settings"], self)
        self._logger.debug(f"Setting: {prettify_map(self._settings.to_dict())}")
        self._logger.info("Loaded settings")
        self._controller.deserialize(session["controller"])
        self._logger.info("Loaded controller")
        self._backend.deserialize(session["backend"])
        self._logger.info("Loaded backend")
        self._annotation_widget.deserialize(session["annotation_widget"])
        self._logger.info("Loaded annotation widget")

        # Reconnect the signals
        scatter_widgets = self._annotation_widget.get_scatter_widgets()

        for widget in scatter_widgets.values():
            self._controller.sign_sample_state_changed.connect(
                    widget.on_sample_state_change
            )
            widget.sign_user_selected_sample.connect(
                    self._controller.on_user_selected_sample
            )
            widget.sign_user_set_sample.connect(
                    self._controller.on_user_set_sample
            )
            widget.sign_ready.connect(
                    self._controller.on_sync_state
            )

            self._controller.sign_state.connect(
                    widget.on_state_update
            )

        # Manually update the state of the application
        self._controller.on_sync_state()
        self._controller.was_updated = False

    @Slot(str, str)
    def _show_dialog(self, msg: str, kind: str = "critical") -> None:
        '''
        Shows certain type of dialog with the given importance.

        Parameters
        ----------
        msg: str
            The message to show
        kind: str, optional. {"critical","warning", "information"}
            The criticality of the message. Default "critical"

        '''
        assert kind in _VALID_MSG_BOXES, ("kind must be one of "
                                          f"{', '.join(_VALID_MSG_BOXES)} ")
        if kind == "information":
            ret = QMessageBox.information(self, "TSExplorer", msg)
        elif kind == "warning":
            ret = QMessageBox.warning(self, "TSExplorer", msg)
        else:
            ret = QMessageBox.critical(self, "TSExplorer", msg)
        return ret

    @Slot()
    def _set_status_msg(self, msg: str, timeout: int = 10):
        '''
        Sets the message of the status bar for the specified amount of time

        Parameters
        ----------
        msg: str
            The message to set
        timeout: int, optional
            The time that the message is shown in SECONDS. Default 10
        '''
        self.statusBar().showMessage(msg, timeout*_SECOND)

    @Slot()
    def _load_sess(self):
        ''' Tries to load a session from user selected archive '''
        cwd = pathlib.Path.cwd()
        filename, _ = QFileDialog.getOpenFileName(
                self, "Select session to load", str(cwd), "Yaml(*.yaml *.yml)"
        )

        # The user cancelled the operation
        if len(filename) == 0:
            return

        fpath = pathlib.Path(filename)
        if not fpath.exists() or not fpath.is_file():
            self._show_dialog(
                    f"Could not find user selected file: {str(fpath)!r}",
                    "warning"
            )
            return

        self.sign_request_state_load.emit(str(fpath))

    @Slot()
    def _save_sess(self):
        '''Saves the current annotation session'''
        # The saved session contains the current user config, annotated files,
        # order of those files, and already made annotations
        if "save_path" not in self._settings:
            self._save_sess_as()
            return

        ok = self._save_sess_impl(self._settings.save_path)
        if ok:
            self._set_status_msg(
                f"Saved session to {self._settings.save_path!r}", 2
            )

    @Slot()
    def _save_sess_as(self):
        '''Saves the current annotation session with the given name'''

        cwd = pathlib.Path.cwd()
        filename, _ = QFileDialog.getSaveFileName(
                self, "Path to save file", str(cwd), "Yaml(*.yml *.yaml)"
        )
        if filename == "":
            self._logger.debug("Saving cancelled by the user")
            return
        ok = self._save_sess_impl(filename)

        # If the saving failed, don't save the filepath, and don't print
        # the message about the successful operation
        if not ok:
            return

        self._settings["save_path"] = filename
        self._set_status_msg(
                f"Saved session to {self._settings.save_path!r}", 2
        )

    @Slot()
    def _remove_session(self):
        '''
        Removes a user-selected session. NOTE: Current session cannot be
        removed.
        '''
        cwd = pathlib.Path.cwd()
        filename, _ = QFileDialog.getOpenFileName(
                self, "Path to save file", str(cwd), "Yaml(*.yml *.yaml)"
        )

        if filename == "":
            self._logger.debug("User cancelled removal")
            return

        fpath = pathlib.Path(filename)
        # Load the user selected file
        session = io.load_yaml(fpath)
        sess_path = session["settings"]["session_path"]

        # You cannot remove the current path
        if sess_path == self._settings.session_path:
            self._show_dialog("Current session cannot be removed!", "warning")
            return

        # Otherwise, just remove the directory
        sess_path = pathlib.Path(sess_path)

        if not sess_path.exists() or not sess_path.is_dir():
            self._logger.debug(("Missing session path: "
                                f"{str(sess_path)!r}! Aborting..."))
            self._show_dialog(
                    f"Missing session directory {str(sess_path)!r}",
                    "warning"
            )
            return

        io.rm_dir(sess_path)

        # Lastly remove the session file.
        if not fpath.is_file() or not fpath.exists():
            self._show_dialog(f"{filename!r} doesn't point to a valid file!")
            return

        fpath.unlink()
        self._logger.debug("Removed session file")
        self._show_dialog(
                f"Removed session {filename} successfully", "information"
        )

    @Slot()
    def _clear_sessions(self):
        ''' Clears all sessions stored in 'user-data-path' '''
        user_data_path = get_user_data_directory(["tsexplorer"])
        session_path = pathlib.Path(self._settings.session_path)
        fdir = [fdir for fdir in user_data_path.iterdir() if fdir != session_path]
        for savedir in fdir:
            io.rm_dir(savedir)
            self._logger.debug(f"Removed {str(fdir)!r}")
        if len(fdir) == 0:
            self._show_dialog("No sessions to remove", "information")
        else:
            dirs_text = "\n".join(
                    str(savedir.relative_to(user_data_path)) for savedir in fdir
            )
            txt = f"Removed the following directories: \n{dirs_text}"
            self._show_dialog(txt, "information")

    @Slot()
    def _export_annotations(self):
        '''Exports the annotations as csv file'''
        n_annotated_samples = self._controller.get_annotation_count()
        if n_annotated_samples == 0:
            self._show_dialog(
                    "There are no annotated samples yet!", "warning"
            )
            return

        try:
            annotations = self._controller.export_annotations()
        except Exception as e:
            self._show_dialog(
                    f"Could not export annotations: {str(e)}", "critical"
            )
            return

        cwd = pathlib.Path.cwd()
        filename, _ = QFileDialog.getSaveFileName(
                self, "Path to save file", str(cwd), "Csv(*.csv)"
        )

        # The user cancelled the export
        if filename == "":
            self._set_status_msg("Export cancelled", 2)
            return

        # Add the annotator as the first row in the output
        annotator_id = self._settings.annotator
        metadata = f"#annotator,{annotator_id}"

        # The payload here is not really "compliant", and thus we don't want
        # to write it using pandas, but rather use a self-written csv-writer
        try:
            io.dump_csv_raw(filename, annotations, metadata=[metadata])
        except Exception as e:
            self._show_dialog(f"Error during export: {str(e)}", "critical")

    @Slot()
    def _reload_config(self):
        '''Reloads the configuration file'''
        old_settings = copy.deepcopy(self._settings.to_dict())
        try:
            settings = self._load_settings(old_settings["filepath"])
            self._settings = settings

            name = self._settings.backend.get("name")
            old_be = old_settings["backend"]["name"]
            if old_be != name:
                raise Exception(("Changing backend is not supported! "
                                f"Old: {old_be!r}, new: {name!r}"))
            # Similarly, change in the labels, or annotator is prohibited.
            old_annotator = old_settings["annotator"]
            if old_annotator != self._settings.annotator:
                raise Exception(("Changing annotator is not supported! "
                                 f"Old: {old_annotator!r}, "
                                 f"new: {self._settings.annotator}"))

            old_labels = set(old_settings["labels"])
            new_labels = set(self.settings.labels)
            if old_labels != new_labels:
                diff = [la for la in new_labels if la not in old_labels]
                raise Exception(("Changing labels is not supported!"
                                 f" Difference: {diff}"))

            # Add the session path from the old-settings if it exists
            if "session_path" in old_settings:
                self._settings["session_path"] = old_settings["session_path"]

            # Reload the AnnotationWidget
            self._annotation_widget.reload()

            # Retrieve all scatter widgets to connect necessary signals
            scatter_widgets = self._annotation_widget.get_scatter_widgets()

            # Connect changes in database to the value
            for widget in scatter_widgets.values():
                self._controller.sign_sample_state_changed.connect(
                        widget.on_sample_state_change
                )
                widget.sign_user_selected_sample.connect(
                        self._controller.on_user_selected_sample
                )
                widget.sign_ready.connect(
                        self._controller.on_sync_state
                )

                self._controller.sign_state.connect(
                    widget.on_state_update
                )

        # If the loading fails, we just restore old settings. However,
        # restoring the old state of backend and other components is not
        # currently possible and thus the application might be left in unstable
        # state.
        except Exception as e:
            self._show_dialog(
                    (f"Error while reloading config: {str(e)}! The state of "
                     "the application is undefined, restart required!"),
                    "critical"
            )

    @Slot()
    def _on_last_sample(self):
        '''Informs the user that last sample is set'''
        self._set_status_msg("NOTE: This is last sample to annotate", 5)

    @Slot()
    def _on_open_dialog(self):
        '''
        Opens a dialog if the widget is not ready, or if it does not already
        exist.
        '''
        if self._is_ready:
            return

        self._dialog = QProgressDialog(
                "Loading widgets", "", 0, 100, parent=self
        )
        self._dialog.setCancelButton(None)

        # Update the progress
        if self._current_progress is not None:
            self._dialog.setValue(self._current_progress)

        self._dialog.exec()

    @Slot(int)
    def _on_progress_update(self, progress: int):
        '''
        Updates the progress of the progress dialog, if it exists

        Parameters
        ----------
        progress: int
            The current progress. Should be a value between 0 and 100.
        '''
        # If dialog exists already, update its value
        if self._dialog is not None:
            self._logger.debug("Set new value")
            self._dialog.setValue(progress)
        # If it does not exist, but the widget is not ready, store the current
        # progress for later use
        elif not self._is_ready:
            self._current_progress = progress

    @Slot()
    def _on_ready(self):
        '''
        Called when the widget is 'ready'. Closes the progress dialog if one
        exists
        '''
        self._logger.debug("on-ready!")
        self._is_ready = True
        if self._dialog is not None:
            self._dialog.close()
            self._dialog = None
            self._current_progress = None
