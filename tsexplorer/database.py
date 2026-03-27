""" Defines the database, and the required tables for the application"""

from .utils import logger
from .metadata import SQLException

from typing import Any, Union, Iterable, Mapping, Tuple, List, Optional
from collections import namedtuple
from PySide6.QtSql import QSqlDatabase, QSqlQuery, QSqlError
_DRIVER: str = "QSQLITE"  # Sqlite 3 is used as the database

_logger = logger.get_logger("database")


# ====== THE SCHEMA FOR THE DATABASE =====
# Use only one table -> Simple and easy to keep in sync.
# The table contains the following columns:
#  * sid: integer, primary key.
#    - This is the id of a given sample. Corresponds to the alphabetical order
#    - of the filename in the folder
#  * ordernumber: integer
#    - An automatically incremented integer which tells the order in which the
#    samples were GIVEN to the user (not necessarily annotated in that order)
#  * status: string, not Null
#    - Status of the sample: Either selected, annotated or unlabeled. See
#    SampleStatus enum
#  * label: string
#    - Any label specified in the configuration file
#  * cluster_id: integer
#    - The id of the cluster where the sample is located in the selector.
#    is null with selectors not supporting sample clustering.

def create_connection(dbname: str, conn_name: str) -> QSqlDatabase:
    '''
    Tries to create connection to the database, and create the tables if
    needed.

    Parameters
    ----------
    dbname: str
        The name of the database. If database with given name doesn't exists
        a new one is made.
    conn_name: str
        The name of the connection. Should be unique during the application
        lifetime

    Raises
    ------
    ConnectionError
        If the connection to the database cannot be created
    RuntimeError
        If the table creation fails

    Returns
    -------
    QSqlDatabase
        The created connection
    '''
    connection = QSqlDatabase.addDatabase(_DRIVER, conn_name)
    connection.setDatabaseName(dbname)
    if not connection.open():
        raise ConnectionError(("Error while creating connection: "
                               f"{connection.lastError().databaseText()}"))
    if not _create_annotation_table(connection):
        raise SQLException("Failed to create the table!")
    return connection


def add_connection(dbname: str, conn_name: str) -> QSqlDatabase:
    '''
    Creates a connection to a given table. NOTE: The name should be
    unique to the application. If it is not, the existing connection
    among the name will be overridden.

    Parameters
    ----------
    dbname: str
        The name of the database to which the connection is created.
    conn_name: str
        The name of the connection. Should be unique through the lifetime of the
        application

    Raises
    ------
    ConnectionError
        If the connection cannot be opened to the given database.

    Returns
    -------
    QSqlDatabase The connection to the database. '''
    connection = QSqlDatabase(_DRIVER, conn_name)
    connection.setDatabaseName(dbname)
    if not connection.open():
        raise ConnectionError(("Error while adding connection: "
                              f"{connection.lastError().databaseText()}"))
    return connection


def remove_connection(conn: QSqlDatabase):
    '''
    Removes the given connection from the available connections, and thus makes
    it impossible to open that connection again.

    Parameters
    ----------
    conn: QSqlDatabase
        The database to connect.
    '''
    QSqlDatabase.removeDatabase(conn.connectionName())


def get_row_count(conn: QSqlDatabase, table_name: str) -> int:
    '''
    Queries the number of items in the given table.

    NOTE: The table name is NOT
    sanitized! Use with caution.

    Parameters
    ----------
    conn: QSqlDatabase
        Connection to the used database.
    table_name: str
        The name of the table to query.

    Returns
    -------
    The number of items to query.

    Raises
    ------
    SQLException
        If there is any problems executing the query
    '''
    query = QSqlQuery(conn)
    success = query.exec(
            f"SELECT COUNT(*) FROM {table_name}"
    )
    if not success:
        err_msg = query.lastError().databaseText()
        raise SQLException(f"Query to {table_name!r} failed: {err_msg!r}")

    if not query.next():
        err_msg = query.lastError().databaseText()
        raise SQLException(f"Error while fetching record: {err_msg}")

    return int(query.value(0))


def add_rows(
        conn: QSqlDatabase,
        data: Union[List[Tuple[int, str, str]], Tuple[int, str, str]],
        table_name: str
        ):

    '''
    Add new rows to the database.

    Parameters
    ----------
    conn: QSqlDatabase
        Connection to the database.
    data: List[Tuple[int, str, str, int]] | Tuple[int, str, str, int]
        The data for the rows that should be added to the table.
    table_name: str
        The name of the table where the rows are added

    Raises
    ------
    SQLException
        If the transaction with the database fails
    '''
    # If a single row is added (i.e. only one tuple is given, convert it to a
    # list for compatibility
    if isinstance(data, tuple):
        data = [data]

    _logger.debug(f"Adding to {table_name!r}")
    query = QSqlQuery(conn)
    res = query.prepare(
            f"""INSERT INTO {table_name} (
                sid, ordernumber, status, label, clusterid
            )
            VALUES (
                :sid, (SELECT IFNULL(MAX(ordernumber) + 1, 0) from {table_name}),
                :status, :label, :clusterid
            )
            """
    )

    _logger.debug(f"'prepare' ok?: {res}")
    for sid, status, label, cluster_id in data:
        query.bindValue(":sid",  int(sid))
        query.bindValue(":status", status)
        query.bindValue(":label", label)
        query.bindValue(":clusterid", cluster_id)

        if not query.exec():
            err_msg = query.lastError().databaseText()
            raise SQLException(
                f"Failed to add row for sample {sid}: {err_msg!r}"
            )


def update_row(
        conn: QSqlDatabase, conditions: Mapping[str, Any],
        payload: Mapping[str, Any], table_name: str
        ) -> bool:
    '''
    Updates a single row from the database. NOTE: No checking is done for the
    validity of the update.

    Parameters
    ----------
    conn: QSqlDatabase
        The connection to the database.
    conditions: Mapping[str, Any]
        The conditions used to select the rows. Should have form column: value
    payload: Mapping[str, Any]
        A mapping containing the columns to update as keys, and the updated
        values as values.
    table_name: str
        The name of the table to update.

    Raises
    ------
    SQLException
        If the update fails
    '''
    _logger.debug(f"Update_row: {payload}")
    query = QSqlQuery(conn)
    update_cols = ", ".join(f"{key} = :{key}" for key in payload.keys())
    cond = ", ".join(f"{key} = :{key}" for key in conditions.keys())

    ret = query.prepare(
        f"""UPDATE {table_name}
        SET {update_cols}
        WHERE {cond}
        """
    )
    _logger.debug(f"'prepare' ok?: {ret}")

    # Bind the values to be updated, and the conditions
    for key, value in payload.items():
        query.bindValue(f":{key}", value)

    for key, value in conditions.items():
        query.bindValue(f":{key}", value)

    if not query.exec():
        err_msg = query.lastError().databaseText()
        raise SQLException(f"Failed to update the rows: {err_msg!r}")


def query(
        conn: QSqlDatabase, query_string: str,
        columns: Optional[Iterable[str]] = None,
        indices: Optional[Iterable[int]] = None
        ) -> List[Tuple[Any, ...]]:
    '''
    Makes an arbitrary query to the database. It's the user's responsibility
    to ensure that the defined query is valid, and doesn't contain any critical
    vulnerabilities.

    Parameters
    ----------
    conn: QSqlDatabase
        The connection to the database.
    query_string: str
        The query that should be executed
    columns: Optional[Iterable[str]]
        The names of the columns that should be retrieved from the query. NOTE:
        this is a mutually exclusive option with 'indices' parameter.
        Default None
    indices: Optional[Iterable[str]]
        The indexes of the columns that should be retrieved from the query.
        NOTE: This is a mutually exclusive option with 'columns' parameter.
        Default None

    Returns
    -------
    List[Tuple[Any, ...]]
        Returns a tuple containing whatever was returned from the query. If
        'columns' option was used, the returned tuple will be namedtuple. NOTE:
        NULL values will be represented as None.

    Raises
    ------
    SQLException
        If the specified query fails.
    '''

    if columns is None and indices is None:
        raise ValueError("Either 'columns' or 'indices' must be specified!")

    elif columns is not None and indices is not None:
        raise ValueError(("'columns' and 'indices' cannot be specified at the "
                          "same time!"))

    query = QSqlQuery(conn)
    if not query.exec(query_string):
        err_msg = query.lastError().databaseText()
        raise SQLException(f"Query failed: {err_msg}")

    if columns is not None:
        Result = namedtuple("Result", columns, rename=True)
        result_obj = Result._make
        indices = [query.record().indexOf(key) for key in columns]
    else:
        result_obj = tuple

    out = []
    while query.next():
        tmp = []
        for ind, key in zip(indices, columns):
            _logger.debug(f"Processing index: {ind} ({key})")
            # Test with name
            val = query.value(ind)

            if query.isNull(ind) and val == '':
                tmp.append(None)
            else:
                tmp.append(val)
        out.append(result_obj(tmp))
    return out


def _create_annotation_table(conn: QSqlDatabase) -> bool:
    '''
    Creates the table definition for the 'annotations' table.

    Parameters
    ----------
    conn: QSqlDatabase
        The connection to the database
    
    Returns
    ------
    bool
        True if the query ran successfully, False otherwise
    '''
    table_creation_query = QSqlQuery(conn)
    return table_creation_query.exec(
        """
        CREATE TABLE IF NOT EXISTS annotations (
            sid INTEGER PRIMARY KEY UNIQUE NOT NULL,
            ordernumber INTEGER UNIQUE NOT NULL,
            status VARCHAR(10) NOT NULL,
            label VARCHAR(50),
            clusterid INTEGER
        )
        """
    )
