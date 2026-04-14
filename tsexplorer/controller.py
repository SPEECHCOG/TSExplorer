''' This file implements a controller class for managing interactions between
    the different stateful components in the application
'''

from . import database
from .metadata import SampleID, Path, SampleState, SQLException
from .utils import logger

from PySide6.QtCore import QObject, Signal, Slot
from typing import Optional, Dict, Any, Union, Mapping
import pathlib
import os

import numpy as np
# NOTE: Currently only samples that are displayed get added to the database.
# Other samples won't be saved until they are added to the database


class Controller(QObject):
    '''
    A controller class that acts as a waypoint to modify and access the database.
    All interactions with the database should come through one of these.

    Signals
    -------
    sign_request_sample
        Emitted when a new sample is required from the backend.
    sign_return_sample: int, object, int
        Emitted when new sample is selected. Contains the sample id, (possible)
        label and the order number
    sign_user_selected_sample: SampleID
        Emitted when user selected a sample that was valid.
    sign_sample_selected: object
        Emitted when a sample is selected to be annotated.
    sign_sample_state_change: int, str
        Emitted when a state of a sample is changed.
    sign_state: list
        Emitted when "on_sync_state" is called. Contains the most up to date
        version of the values in the database
    sign_last_sample:
        Emitted when there is no more samples to annotate. NOTE: Will be
        emitted only when last sample is really annotated!
    sign_error: str
        Emitted when the operations with the database fail in catastrophic
        manner
    '''
    sign_request_sample = Signal(name="sign_request_sample")
    sign_return_sample = Signal(int, object, int, name="sign_return_sample")
    sign_sample_state_changed = Signal(
            int, str, name="sign_sample_state_changed"
    )
    sign_state = Signal(list, name="sign_state")
    sign_last_sample = Signal(name="sign_last_sample")
    sign_error = Signal(str, name="sign_error")

    def __init__(
            self, session_path: Union[str, os.PathLike],
            n_samples: int,
            table_name: str = "annotations",
            parent: Optional[QObject] = None,
            labels: Optional[list] = None,
            base_labels_numpy_file: Optional[str] = None,
            session_loaded: bool = False
            ):
        '''
        Constructs the controller.

        Parameters
        ----------
        session_path: str | os.PathLike
            Path to the directory where the database will be stored. Should be
            initialized (i.e. all missing directories should be already
            constructed).
        n_samples: int
            The total amount of samples in the database.
        table_name: str, Optional
            The name of the created table. Default "annotations"
        parent: Optional[QObject]
            The parent of this object. Default None
        '''
        super().__init__(parent)

        db_path = pathlib.Path(session_path) / "annotations.sqlite3"

        # Must have connection to the database.
        self._db_path: pathlib.Path = db_path
        self._conn = database.create_connection(str(db_path), "controller")

        # subscribe to notifications on the database
        self._driver = self._conn.driver()
        self._driver.subscribeToNotification(table_name)
        self._driver.notification.connect(self._on_notification)

        # Keeps count on if project was updated after save.
        self._was_updated: bool = False

        self._table_name: str = table_name
        self._n_samples = n_samples

        self._logger = logger.get_logger("controller")
        self._logger.info(f"Storing data to {db_path}")
        self._logger.debug(f"Open connections: {self._conn.connectionNames()}")
        
        self._labels_from_config = labels or []
        self._base_labels_file = base_labels_numpy_file
        self._session_loaded = session_loaded
        
        if (self._base_labels_file is not None) and (not self._session_loaded):
            self.load_base_labels(self._base_labels_file)

    @property
    def db_path(self) -> pathlib.Path:
        ''' Returns the currently used location for the database.'''
        return self._db_path

    @property
    def default_table(self) -> str:
        '''Returns the default table-name used for all operations'''
        return self._table_name

    @property
    def was_updated(self) -> str:
        '''
        Returns True if the table was updated after last reset of this variable
        '''
        return self._was_updated

    @was_updated.setter
    def was_updated(self, value: bool):
        '''
        Updates the value of property 'was_updated'
        '''
        self._was_updated = value

    def get_amount_of_samples(self, table_name: Optional[str] = None) -> int:
        '''
        Returns the amount of samples stored in the database, regardless their
        status.

        Parameters
        ----------
        table_name: Optional[str]
            The table where the annotations are stored. If None, the default
            table name is used. Default None

        Returns
        -------
        int
            The amount of samples in the given table.
        '''
        table_name = table_name or self._table_name

        try:
            res = database.query(
                self._conn,
                f"""SELECT COUNT(*) as amount FROM {table_name}""",
                columns=["amount"]
            )
            return res[0].amount
        except SQLException as e:
            self.sign_error.emit(f"Database error: {str(e)}")
            return None

    def get_annotation_count(self, table_name: Optional[str] = None) -> int:
        '''
        Returns the amount of annotated samples

        Parameters
        ----------
        table_name: Optional[str]
            The table where the annotations are stored. If None, the default
            table name is used. Default None

        Returns
        -------
        int
            The amount of annotations in the given table.

        '''
        if table_name is None:
            table_name = self._table_name

        try:
            res = database.query(
                    self._conn,
                    f"""SELECT COUNT(*) as amount FROM {table_name}
                    WHERE label IS NOT NULL AND status = 'annotated'""",
                    columns=["amount"]
            )
            return res[0].amount
        except SQLException as e:
            self.sign_error.emit(f"Database error: {str(e)}")
            return None

    def was_annotated(self) -> bool:
        '''
        Checks if any annotations were made.

        Returns
        -------
        bool:
            True if some annotations were made (i.e. the state of the
            db has changed), False otherwise.
        '''

        n_annotations = self.get_annotation_count()
        return n_annotations != 0

    def close_session(self):
        '''
        Closes the session to the created database, and removes the
        connection, so it can not be opened again anymore.
        '''
        if self._conn.isOpen():
            self._conn.close()
        self._logger.debug("Closed connection")
        database.remove_connection(self._conn)
        self._logger.debug("Removed connection from DB")

    def remove_db(self):
        '''
        Removes the current database from the filesystem. NOTE: Should be
        called only when all connections to the database are closed!

        Raises
        ------
        FileNotFoundError
            If the database file cannot be found
        '''
        self._db_path.unlink(missing_ok=False)
    
    def load_base_labels(self, fpath: str):
        import numpy as np

        arr = np.load(fpath, allow_pickle=True)
        if len(arr) != self._n_samples:
            raise ValueError(
                f"Base label file contains {len(arr)} labels but dataset has {self._n_samples}"
            )

        # Validate unique labels
        valid = set(self._labels_from_config) | {str(SampleState.UNLABELED)}
        unknown = set(arr) - valid
        if unknown:
            raise ValueError(f"Invalid labels found in base label file: {unknown}")

        # Apply all labels to DB
        for sid, label in enumerate(arr):
            try:
                # Try inserting a new row
                database.add_rows(
                    self._conn,
                    (
                        sid,
                        SampleState.ANNOTATED if label != str(SampleState.UNLABELED) else SampleState.UNLABELED,
                        label,
                        None,
                    ),
                    self._table_name,
                )
            except SQLException:
                # If row exists -> update it
                database.update_row(
                    self._conn,
                    {"sid": sid},
                    {
                        "status": SampleState.ANNOTATED
                        if label != str(SampleState.UNLABELED)
                        else SampleState.UNLABELED,
                        "label": label,
                    },
                    self._table_name,
                )

            # Notify UI so scatter plots and widgets update
            self.sign_sample_state_changed.emit(sid, label)

    @Slot()
    def on_request_sample(self, order_num: int, table_name: Optional[str] = None):
        '''
        Returns the asked sample. If the given sample is completely new,
        checks if user has selected sample. If not, requests the backend to
        generate a new sample.

        Parameters
        ----------
        order_num: int
            The order number. If larger than the current maximum order number,
            a new sample is generated.

        table_name: Optional[str]
            The name of the table to query. If left None, the default table
            (passed to the constructor) is used. Default None

        Raises
        ------
        RuntimeError
            If the given table doesn't exist
        '''

        if table_name is None:
            table_name = self._table_name

        if table_name not in self._conn.tables():
            raise RuntimeError(f"Unknown table {table_name!r}")

        n_annotations = self.get_annotation_count(table_name)
        n_items = self.get_amount_of_samples(table_name)
        self._logger.debug((f"Database contains {n_items} samples "
                            f"({n_annotations} annotated), "
                            f"retrieving sample {order_num}"))

        is_last_sample = order_num == self._n_samples - 1

        # First, try to retrieve the sample with the exact order number
        # This ensures that previously visited samples (including labeled ones)
        # can be retrieved when using the "previous sample" button
        try:
            values = database.query(
                self._conn,
                f"""SELECT sid, label FROM {table_name}
                    WHERE ordernumber = {order_num}
                    ORDER BY ordernumber""",
                columns=["sid", "label"]
            )
            self._logger.debug(f"Exact order query result: {values}")
        except SQLException as e:
            self._logger.error(f"Exact order query failed: {str(e)}")
            self.sign_error.emit(f"Database error: {str(e)}")
            return

        if len(values) != 0:
            sample = values[0]
            self._logger.debug(f"Returning sample with exact order {sample.sid} {sample.label!r}")
            self.sign_return_sample.emit(sample.sid, sample.label, order_num)

            if is_last_sample:
                self.sign_last_sample.emit()
            return

        # If no sample with the exact order number is found, continue with normal logic

        # First, we query if the database has any queued samples selected.
        try:
            values = database.query(
                self._conn,
                (f"SELECT sid, label FROM {table_name} "
                 f"WHERE status = 'selected' "
                 "ORDER BY ordernumber"),
                columns=["sid", "label"]
            )
            self._logger.debug(f"Query result: {values}")
        except SQLException as e:
            self._logger.error(f"Query failed: {str(e)}")
            self.sign_error.emit(f"Database error: {str(e)}")
            return

        # If there are queried samples, use those first.
        if len(values) != 0:
            sample = values[0]
            self._logger.debug(f"Queued sample {sample.sid} {sample.label!r}")
            self.sign_return_sample.emit(sample.sid, sample.label, order_num)

            if is_last_sample:
                self.sign_last_sample.emit()
            return

        # If there are no queued samples, try to find the next unlabeled sample
        try:
            values = database.query(
                self._conn,
                (f"SELECT sid, label FROM {table_name} "
                 f"WHERE status = '{SampleState.UNLABELED.name}' "
                 "ORDER BY ordernumber"),
                columns=["sid", "label"]
            )
            self._logger.debug(f"Unlabeled query result: {values}")
        except SQLException as e:
            self._logger.error(f"Unlabeled query failed: {str(e)}")
            self.sign_error.emit(f"Database error: {str(e)}")
            return

        if len(values) != 0:
            sample = values[0]
            self._logger.debug(f"Unlabeled sample {sample.sid} {sample.label!r}")
            self.sign_return_sample.emit(sample.sid, sample.label, order_num)

            if is_last_sample:
                self.sign_last_sample.emit()
            return

        # If there are no unlabeled samples either, fallback to retrieving old sample
        try:
            values = database.query(
                self._conn,
                (f"SELECT sid, label FROM {table_name} "
                 f"WHERE status != 'annotated' "
                 f"AND ordernumber > {order_num} "
                 "ORDER BY ordernumber"),
                columns=["sid", "label"]
            )
            self._logger.debug(f"Fallback query result: {values}")
        except SQLException as e:
            self._logger.error(f"Fallback query failed: {str(e)}")
            self.sign_error.emit(f"Database error: {str(e)}")
            return

        if len(values) != 0:
            sample = values[0]
            self._logger.debug(f"Next unlabeled or selected sample {sample.sid} {sample.label!r}")
            self.sign_return_sample.emit(sample.sid, sample.label, order_num)

            if is_last_sample:
                self.sign_last_sample.emit()
            return

        # Otherwise, just ask the backend to generate a new sample
        self._logger.debug("Generating a new sample")
        self.sign_request_sample.emit()

        if is_last_sample:
            self.sign_last_sample.emit()

    @Slot()
    def on_new_sample(self, new_sample: SampleID, cluster_id: Optional[int]):
        '''
        Updates the database of the new sample, and propagates the information
        about the just selected sample. NOTE: Doesn't inform listeners of
        "sign_sample_state_changed" to avoid rewrite of the displayed data.

        Parameters
        ----------
        new_sample: SampleID
            The selected __new__ sample

        cluster_id: Optional[int]
            The cluster ID of the given sample. Can be None, if the backend
            does not support sample clustering, or if the cluster ID cannot
            be inferred selection time
        '''
        if isinstance(new_sample, (list, np.ndarray)):
            new_sample = new_sample[0]

        self._logger.debug(f"Adding new samples: {new_sample}")
        try:
            database.add_rows(
                    self._conn,
                    (new_sample, SampleState.SELECTED, None, cluster_id),
                    self._table_name
            )

            # Find out the order number
            res = database.query(
                    self._conn,
                    f"""SELECT ordernumber FROM {self._table_name}
                        WHERE sid = {new_sample}
                    """,
                    columns=["ordernumber"]
            )

            if len(res) != 1:
                raise SQLException(f"Expected 1 match, got {len(res)}")

            order_num = res[0].ordernumber
        except SQLException as e:
            self._logger.critical(("Failed to add new row for sample "
                                   f"{new_sample}: {str(e)}"))
            self.sign_error.emit(f"Database error: {str(e)}")
            return
        else:
            self.sign_return_sample.emit(new_sample, None, order_num)

    @Slot()
    def on_user_selected_sample(self, sample_id: SampleID):
        '''
        Registers the user selected samples.

        Parameters
        ----------
        sample_id: SampleID
            The sample selected by the user
        '''
        # First, check the status of the sample from the database
        try:
            res = database.query(
                self._conn,
                f"""
                SELECT label, status FROM {self._table_name}
                WHERE sid = {sample_id}
                """, columns=["label", "status"]
            )
        except SQLException as e:
            self._logger.error((f"State check of sample {sample_id} failed: "
                                f"{str(e)}"))
            self.sign_error.emit(f"Database error: {str(e)}")
            return

        self._logger.debug(f"Query result: {res}")

        # Always append the sample to the end of the queue regardless of its current state
        try:
            res_order = database.query(
                self._conn,
                f"SELECT MAX(ordernumber) as max_order FROM {self._table_name}",
                columns=["max_order"]
            )
            max_order = res_order[0].max_order
            new_order = 0 if max_order is None else max_order + 1
        except SQLException as e:
            self._logger.error(f"Failed to get max order number: {str(e)}")
            self.sign_error.emit(f"Database error: {str(e)}")
            return

        # Possible cases:
        # 1. Sample is not found in db -> Add sample to db, signal "selected"
        # 2. Sample is in db -> Re-queue it by updating its status and order number

        # case 1
        if len(res) == 0:
            self._logger.debug(f"Sample {sample_id} not in db, adding it ")

            try:
                database.add_rows(
                    self._conn, (sample_id, SampleState.SELECTED, None, None),
                    self._table_name
                )
                database.update_row(
                    self._conn, {"sid": sample_id},
                    {"ordernumber": new_order}, self._table_name
                )
            except SQLException as e:
                self._logger.error(("failed to add row for sample "
                                    f"{sample_id}: {str(e)}"))
                self.sign_error.emit(f"Database error: {str(e)}")
                return
            else:
                self.sign_sample_state_changed.emit(
                    sample_id, SampleState.SELECTED
                )
                return

        # case 2
        label, status = res[0]

        # Re-queue the sample regardless of its current status
        try:
            database.update_row(
                self._conn, {"sid": sample_id},
                {"status": SampleState.SELECTED, "ordernumber": new_order},
                self._table_name
            )
        except SQLException as e:
            self._logger.error((f"Failed to update db for sample {sample_id}: "
                                f"{str(e)}"))
            self.sign_error.emit(f"Database error: {str(e)}")
        else:
            self.sign_sample_state_changed.emit(sample_id, SampleState.SELECTED)


    @Slot()
    def on_user_set_sample(self, sample_id: SampleID):
        '''
        This handler is called when the user sets a new sample from the
        database.

        Parameters
        ----------
        sample_id: SampleID
            The sample to the set as the currently annotated sample

        '''
        # First, check the status of the sample from the database
        try:
            res = database.query(
                    self._conn,
                    f"""
                    SELECT label, ordernumber FROM {self._table_name}
                    WHERE sid = {sample_id}
                    """, columns=["label", "ordernumber"]
            )

            # Possible cases:
            # 1. The sample is not in the db -> Add the sample, and notify
            #   other components about the new selected sample.
            # 2. The sample is in the DB -> Just notify the other components
            #   that this sample is selected.

            # case 1
            # NOTE: we must also check if the sample is the last sample, and
            # set the status accordingly
            if len(res) == 0:
                self._logger.debug((f"Sample {sample_id} not in db, adding "
                                    "it now"))
                database.add_rows(
                        self._conn,
                        (sample_id, SampleState.SELECTED, None, None),
                        self._table_name
                )
                label = None

                res2 = database.query(
                        self._conn,
                        f"""
                        SELECT ordernumber FROM {self._table_name}
                        WHERE sid = {sample_id}
                        """, columns=["ordernumber"]
                )

                order_num = res2[0].ordernumber
            else:
                label = res[0].label
                order_num = res[0].ordernumber

            is_last_sample = order_num == self._n_samples - 1

            # case 1 & 2 -> Notify the other components
            self.sign_return_sample.emit(sample_id, label, order_num)

            if is_last_sample:
                self.sign_last_sample.emit()

        except SQLException as e:
            self._logger.error(("Failed to query database for sample "
                               f"{sample_id}: {str(e)}"))
            self.sign_error.emit(f"Failed to query database: {str(e)}")

    @Slot()
    def on_sample_state_change(self, sid: SampleID, label: str):
        '''
        Updates the given samples state to the database. Assumes that
        the state of the sample is 'annotated'.
        Emits 'sign_sample_state_changed' if the update is successful.

        Parameters
        ----------
        sid: SampleID
            The sample to be updated
        label: str
            The new label for the given sample.

        Raises
        ------
        RuntimeError
            If the update to the database fails.

        '''
        self._logger.debug(f"Updating sample {sid} status")

        # Set the status based on the label. If it is "unlabeled", the status
        # is set to UNLABELED. Otherwise it is updated to ANNOTATED.
        status = (SampleState.ANNOTATED if label != SampleState.UNLABELED
                  else SampleState.UNLABELED)

        try:
            database.update_row(
                    self._conn,
                    {"sid": sid}, {"status": status, "label": label},
                    self._table_name
            )
        except SQLException as e:
            self._logger.error(f"Failed to add row for sample {sid}: {str(e)}")
            self.sign_error.emit(f"Database error: {str(e)}")
        else:
            self.sign_sample_state_changed.emit(sid, label)

    @Slot()
    def on_update_sample(
            self, sample_id: SampleID, payload: Mapping[str, Any]
            ):
        '''
        Updates the status of the given sample. NOTE: Should not be used for
        updating the status of the sample, as this method DOES NOT emit the
        'sign_sample_state_changed' signal.

        Parameters
        ----------
        sample_id: SampleID
            The id of the sample to be updated.
        payload: Mapping[str, Any]
            The data to be updated. Behavior is undefined if contains columns
            that are not in the table.
        '''
        # Check that the sample is located in the database

        try:
            res = database.query(
                    self._conn,
                    f"""SELECT sid FROM {self._table_name}
                        WHERE sid = {sample_id}""",
                    columns=["sid"]
            )

            if len(res) == 0:
                self._logger.error((f"Tried to update sample {sample_id}, "
                                    "which is not in the database!"))
                self.sign_error.emit(("Tried to update sample which is not in "
                                      "database. This is likely a bug"))
                return

            self._logger.debug((f"Updating sample {sample_id} with payload"
                                f" {payload}"))
            # If the sample was found, just update it
            database.update_row(
                    self._conn, {"sid": sample_id}, payload, self._table_name
            )
        except SQLException as e:
            self._logger.error(("Failed to update database for sample "
                                f"{sample_id}: {str(e)}"))
            self.sign_error.emit(f"Database error: {str(e)}")

    @Slot()
    def on_sync_state(self):
        '''
        Retrieves the state of all samples appended to the database, and
        emits the state of them.
        '''
        try:
            values = database.query(
                    self._conn,
                    f"SELECT sid, status, label FROM {self._table_name}",
                    columns=["sid", "status", "label"]
            )
        except SQLException as e:
            self._logger.error(f"Error while querying database: {str(e)}")
            self.sign_error.emit(f"Error while querying database: {str(e)}")
        else:
            self.sign_state.emit(values)

    @Slot()
    def export_annotations(
            self, table_name: Optional[str] = None
            ) -> Dict[str, Any]:
        '''
        Queries the current annotations, and returns them in an easy-to-use
        format

        Parameters
        ----------
        table_name: Optional[str]
            The name of the table to query. If None, the default table name
            given to the constructor is used. Default None.

        Returns
        -------
        Dict[str, Any]
            The labeled samples

        Raises
        ------
        RuntimeError
            If the given table doesn't exist
        SQLException
            If the query to the database fails
        '''
        if table_name is None:
            table_name = self._table_name

        if table_name not in self._conn.tables():
            raise RuntimeError(f"Invalid table {table_name!r}!")
        
        # Query: order by ordernumber to preserve annotation order
        values = database.query(
            self._conn,
            f"""
            SELECT sid, label, clusterid FROM {table_name}
            WHERE label IS NOT NULL AND status = 'annotated'
            ORDER BY ordernumber
            """,
            columns=["sid", "label", "clusterid"]
        )
        sample_ids, labels, cluster_ids = map(lambda data: list(data), zip(*values))

        return {"sample_id": sample_ids, "label": labels, "cluster_id": cluster_ids}

    def serialize(self, session_dir: Path) -> Dict[str, Any]:
        '''
        Serializes all the required information from the session in YAML/JSON
        format.

        Parameters
        ----------
        session_dir: Path
            The path to the currently used session directory.

        Returns
        -------
        Dict[str, Any]
            The serialized session.
        '''
        payload: Dict[str, Any] = {}
        payload["db_path"] = str(self._db_path)
        payload["table_name"] = self._table_name
        return payload

    def deserialize(self, payload: Mapping[str, Any]):
        '''
        Deserializes previously saved state of the application.

        Parameters
        ----------
        payload: Mapping[str, Any]
            The serialized state to load.
        '''

        # Handle the close of the current session, and then open new session
        self.close_session()

        # Remove any traces to the previous connection
        del self._conn

        self._db_path = pathlib.Path(payload["db_path"])
        self._table_name = payload["table_name"]

        # Create new connection
        self._logger.debug(f"Creating connection to {self._db_path}")

        try:
            self._conn = database.create_connection(
                    str(self._db_path), "controller"
            )
            self._logger.debug("Connection opened successfully")

            # re-subscribe to notifications on the database
            self._driver = self._conn.driver()
            self._driver.subscribeToNotification(self._table_name)
            self._driver.notification.connect(self._on_notification)

        except (ConnectionError, SQLException) as e:
            self._logger.critical(("Databased connection initialization "
                                   f"failed: {str(e)}"))
            self.sign_error.emit(f"Failed to initialize the database: {str(e)}")

    @Slot()
    def _on_notification(
            self, table_name: str, source: Any, payload: SampleID
            ):
        '''
        Handler for cases where the database is updated. Unfortunately, Qt does
        not inform about executed action, so we just assume that a table was 
        altered in some way.

        Parameters
        ----------
        table_name: str
            The table that sends the notification
        source: Any
            The source of the notification. Is always 'UnknownSource' for this,
            and thus useless.
        payload: SampleID
            The id of the modified row.
        '''
        self._was_updated = True
