""" Defines a simple Buffer implementation """

from typing import Any, Dict, Tuple, Union
from collections import deque
from ..metadata import SampleID


class Buffer:
    '''
    Simple implementation of FIFO type buffer for arbitrary data.

    '''
    def __init__(self, cap: int):
        '''
        Constructor for the Buffer.

        Parameters
        ----------
        cap: int
            The maximum capacity of the buffer. NOTE: Cannot be changed after
            creation.
        '''
        self._cap: int = cap
        self._ptr: int = 0
        self._buffer: Dict[SampleID, Dict[str, Any]] = {}
        self._order = deque(maxlen=cap)

    def append(self, sample_id: SampleID, widget_name: str, item: Any):
        '''
        Adds the given information to the end of the buffer. If the buffer is
        full, removes the oldest entry from the buffer.

        Parameters
        ----------
        sample_id: SampleID
            The sample ID to which the data is related to.
        widget_name: str
            The name of the widget to which the data is related to.
        item: Any
            The data to append.
        '''
        # If the sample ID exists in the buffer, and we are just trying
        # to append new widget to the existing sample ID
        if sample_id in self._buffer:
            self._buffer[sample_id][widget_name] = item
            return

        # If the buffer is full, and we are adding completely new sample ID
        # we remove the oldest information from the buffer.
        if self._ptr == self._cap:
            top_sample_id = self._order.popleft()
            self._buffer.pop(top_sample_id)
            self._buffer[sample_id] = {widget_name: item}
            self._order.append(sample_id)
        else:
            self._ptr += 1
            self._buffer[sample_id] = {widget_name: item}
            self._order.append(sample_id)

    def pop(self) -> Dict[str, Any]:
        '''
        Removes the item from the buffer that was first first appended.

        Returns
        -------
        Dict[str, Any]
            The removed data.

        Raises
        ------
        IndexError
            If the buffer is empty.
        '''
        if self._ptr == 0:
            raise IndexError("The buffer is empty")
        top_sample_id = self._order.popleft()
        top_element = self._buffer.pop(top_sample_id)
        self._ptr -= 1
        return top_element

    def clear(self):
        '''Clears the internal state of the buffer.'''
        self._ptr = 0
        self._order.clear()
        self._buffer.clear()

    def __contains__(self, sample_id: SampleID) -> bool:
        '''
        Convenience method to support Python's 'x in y' syntax.

        Parameters
        ----------
        sample_id: SampleID
            The id of the sample one wants to check.
        '''
        return sample_id in self._buffer

    def __len__(self) -> int:
        ''' Returns the current length of the buffer'''
        return self._ptr

    def __getitem__(self, index: Union[SampleID, Tuple[SampleID, str]]) -> Any:
        '''
        Convenience method for using Python's indexing syntax 'container[x]'

        Parameters
        ----------
        sample_id: SampleID
            The id of the sample one wants to retrieve from the buffer.

        Raises
        ------
        TypeError
            If multiple indices are used. Only 1 dimensional indexing is
            supported

        IndexError
            If the given sample is not in the buffer
        '''
        # If the indexing is done with a tuple, assume it is
        # (sample_id, widget_name)
        if isinstance(index, tuple) and len(index) != 2:
            raise ValueError(("Only (sample_id, widget_name) indexing is "
                              "supported for tuples!"))

        if isinstance(index, tuple):
            sample_id, wname = index
            vals = self._buffer[sample_id]
            if wname not in vals:
                raise KeyError(f"Unknown key: {wname!r}")
            return vals[wname]

        if index not in self:
            raise IndexError(f"Invalid index {index}")

        return self._buffer[index]
