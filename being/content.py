"""Content manager. Manages spline motions in content directory. Motion model."""
import collections
import glob
import os
from collections import OrderedDict
from typing import Generator

from being.configuration import CONFIG
from being.curve import Curve
from being.logging import get_logger
from being.pubsub import PubSub
from being.serialization import loads, dumps
from being.spline import BPoly, split_spline
from being.utils import SingleInstanceCache, read_file, rootname, write_file


CONTENT_CHANGED = 'CONTENT_CHANGED'
"""String literal for content changed PubSub event."""

DEFAULT_DIRECTORY = CONFIG['General']['CONTENT_DIRECTORY']
"""Default content directory."""


def stripext(p):
    """Strip file extension from path.

    Usage:
        >>> stripext('this/is/a_file.ext')
        'this/is/a_file'
    """
    root, _ = os.path.splitext(p)
    return root


def upgrade_splines_to_curves(directory, logger=None):
    """Go through each JSON file inside directory and upgrade every serialized
    spline to a curve.

    Args:
        directory: Folder to check.
    """
    if logger is None:
        logger = get_logger('upgrade_splines_to_curves()')

    for fp in glob.iglob(directory + '/*.json'):
        obj = loads(read_file(fp))
        if isinstance(obj, Curve):
            pass
        elif isinstance(obj, BPoly):
            curve = Curve(split_spline(obj))
            logger.info('Upgrading spline to curve %r', fp)
            write_file(fp, dumps(curve))
        else:
            logger.warning('Do not know what to do with obj', obj)


class Files(collections.MutableMapping):

    """Wrap files inside directory on disk as dictionary. Iteration order is
    most recently modified.

    Attributes:
        directory: Directory to manage.
        loads: Serialization loader function
        dumps: Serialization dumper function
    """

    def __init__(self, directory: str, loads=loads, dumps=dumps):
        """Args:
            directory: Directory to manage.

        Kwargs:
            loads: Serialization loader function.
            dumps: Serialization dumper function.
        """
        self.directory = directory
        self.loads = loads
        self.dumps = dumps
        os.makedirs(self.directory, exist_ok=True)

    def _fullpath(self, path: str) -> str:
        """Resolve fullpath."""
        return os.path.join(self.directory, path)

    def _recently_modified(self):
        """Iterate over most recently modified paths."""
        filepaths = glob.iglob(self.directory + '/*')
        mostRecently = sorted(filepaths, key=os.path.getctime, reverse=True)
        prefix = self.directory + '/'
        for fp in mostRecently:
            _, path = fp.split(prefix, maxsplit=1)
            yield path

    def __getitem__(self, path: str) -> Generator[str, None, None]:
        fp = self._fullpath(path)
        return self.loads(read_file(fp))

    def __setitem__(self, path: str, value: object):
        fp = self._fullpath(path)
        write_file(fp, self.dumps(value))

    def __delitem__(self, path: str):
        fp = self._fullpath(path)
        os.remove(fp)

    def __iter__(self):
        return iter(self._recently_modified())

    def __len__(self):
        return len(self._recently_modified())

    def __contains__(self, path: str):
        # Skip __iter__
        fp = self._fullpath(path)
        return os.path.exists(fp)

    def __str__(self):
        return '%s(directory=%r)' % (type(self).__name__, self.directory)


class Content(PubSub, SingleInstanceCache):

    """Content manager. For now only motions / splines."""

    # TODO: Extend for all kind of files, subfolders.
    # TODO: NestedDict?

    def __init__(self, directory=DEFAULT_DIRECTORY, data=None, ext='.json'):
        """Kwargs:
            directory: Directory to manage. Default content directory from
                configuration by default.
            data: Data container.
            ext: File extensions. name + ext = path.
        """
        if data is None:
            data = Files(directory)
        else:
            directory = None

        super().__init__(events=[CONTENT_CHANGED])
        self.directory = directory
        self.data = data
        self.ext = ext
        self.logger = get_logger(str(self))

        if self.directory is not None:
            upgrade_splines_to_curves(self.directory, self.logger)

    def curve_exists(self, name: str) -> bool:
        """Check if motion curve exists.

        Args:
            name: Curve name.

        Returns:
            If curve exists.
        """
        return name + self.ext in self.data

    def load_curve(self, name: str) -> BPoly:
        """Load miotion curve from disk.

        Args:
            name: Motion name.

        Returns:
            Spline
        """
        return self.data[name + self.ext]

    def save_curve(self, name: str, curve: BPoly):
        """Save motion curve to disk.

        Args:
            name: Curve name.
            curve: Motion curve to save.
        """
        self.data[name + self.ext] = curve
        self.publish(CONTENT_CHANGED)

    def delete_curve(self, name: str):
        """Delete motion curve from disk.

        Args:
            name: Curve name.
        """
        del self.data[name +  self.ext]
        self.publish(CONTENT_CHANGED)

    def rename_curve(self, oldName: str, newName: str):
        """Rename motion curve.

        Args:
            oldName: Old curve name.
            newName: New curve name.
        """
        oldPath = oldName + self.ext
        newPath = newName + self.ext
        self.data[newPath] = self.data.pop(oldPath)
        self.publish(CONTENT_CHANGED)

    def find_free_name(self, wishName='Untitled'):
        """Find free name. Append numbers starting from 1 if name is already taken.

        Args:
            wishName: Wish name.

        Returns:
            Available version of wish name.

        Raises:
            RuntimeError: If we can not find any available name (after x tries...)
        """
        names = set(map(rootname, self.data))
        if wishName not in names:
            return wishName

        for number in range(1, 100):
            name = f'{wishName} {number}'
            if name not in names:
                return name

        raise RuntimeError('Can not find any free name!')

    def list_curve_names(self) -> list:
        """List current curve names."""
        return list(map(stripext, self.data))

    def forge_message(self) -> OrderedDict:
        """Forge content / motions message."""
        # TODO: Rename type motions -> curves ???
        return OrderedDict([
            ('type', 'motions'),
            ('curves', [
                (stripext(path), motion)
                for path, motion in self.data.items()
            ]),
        ])

    def __str__(self):
        return '%s(directory=%r)' % (type(self).__name__, self.directory)
