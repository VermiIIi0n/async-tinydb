"""
Contains the querying interface.

Starting with :class:`~tinydb.queries.Query` you can construct complex
queries:

>>> ((where("f1") == 5) & (where("f2") != 2)) | where('s').matches(r"^\\w+$")
(("f1" == 5) and ("f2" != 2)) or ('s' ~= ^\\w+$ )

Queries are executed by using the ``__call__``:

>>> q = where("val") == 5
>>> q({"val": 5})
True
>>> q({"val": 1})
False
"""
from __future__ import annotations
import re
from typing import Container, Iterable, Mapping, Callable, Any, NoReturn
from typing import Protocol
from contextlib import suppress
from warnings import warn
from .utils import freeze, is_iterable, supports_in

__all__ = ("Query", "QueryLike", "where")


def is_cacheable(q: QueryLike) -> bool:
    """
    Check if a query is cacheable.

    Returns `True` unless the query contains `is_cacheble()` method
    or `cacheable` property that returns `False`.
    """
    if hasattr(q, "cacheable"):
        return q.cacheable
    if hasattr(q, "is_cacheable"):
        warn("`is_cacheable()` is deprecated, use `cacheable` instead",
             DeprecationWarning)
        return q.is_cacheable()
    warn("QueryLike should have a `cacheable` property", DeprecationWarning)
    return True


class QueryLike(Protocol):
    """
    A typing protocol that acts like a query.

    Something that we use as a query must have three properties:

    1. It must be callable, accepting a `Mapping` object and returning a
        boolean that indicates whether the value matches the query
    2. It must have a `cacheable` attribute that indicates whether the
        query can be cached
    3. it must have a stable hash that will be used for query caching
        if the query is cacheable.

    And of course it should be idempoent for the document it is called

    This query protocol is used to make MyPy correctly support the query
    pattern that TinyDB uses.

    See also 
    https://mypy.readthedocs.io/en/stable/protocols.html#simple-user-defined-protocols
    """

    def __call__(self, value: Mapping) -> bool: ...  # pragma: no cover

    def __hash__(self) -> int: ...  # pragma: no cover

    @property
    def cacheable(self) -> bool: ...  # pragma: no cover


class QueryInstance:
    """
    A query instance.

    This is the object on which the actual query operations are performed. The
    :class:`~asynctinydb.queries.Query` class acts like a query builder and
    generates :class:`~asynctinydb.queries.QueryInstance` objects which will
    evaluate their query against a given document when called.

    Query instances can be combined using logical OR and AND and inverted using
    logical NOT.

    In order to be usable in a query cache, a query needs to have a stable hash
    value with the same query always returning the same hash. That way a query
    instance can be used as a key in a dictionary.
    """

    def __init__(
            self,
            test: Callable[[Mapping], bool],
            frame: tuple,
            cacheable: bool = True):
        self._test = test
        self._frame = frame
        self._cacheable = cacheable

    def is_cacheable(self) -> bool:
        warn("`is_cacheable` is deprecated, use `cacheable` property",
             DeprecationWarning, 2)
        return self._cacheable

    @property
    def cacheable(self) -> bool:
        return self._cacheable

    def __call__(self, value: Mapping) -> bool:
        """
        Evaluate the query to check if it matches a specified value.

        :param value: The value to check.
        :return: Whether the value matches this query.
        """
        return self._test(value)

    def __hash__(self) -> int:
        # We calculate the query hash by using the ``frame`` object which
        # describes this query uniquely, so we can calculate a stable hash
        # value by simply hashing it
        if self.cacheable:
            return hash(self._frame)
        raise TypeError("Cannot hash non-cacheable query")

    def __repr__(self) -> str:
        return f"QueryImpl{self._frame}"

    def __eq__(self, other: object) -> bool:
        if isinstance(other, QueryInstance) and self.cacheable and other.cacheable:
            return self._frame == other._frame
        return False

    # --- Query modifiers -----------------------------------------------------

    def __and__(self, other: QueryInstance) -> QueryInstance:
        # We use a frozenset for the hash as the AND operation is commutative
        # (a & b == b & a) and the frozenset does not consider the order of
        # elements
        frame = ("and", frozenset([self._frame, other._frame]))
        cache = self.cacheable and other.cacheable

        return QueryInstance(
            lambda value: self(value) and other(value), frame, cache)

    def __or__(self, other: QueryInstance) -> QueryInstance:
        # We use a frozenset for the hash as the OR operation is commutative
        # (a | b == b | a) and the frozenset does not consider the order of
        # elements
        frame = ("or", frozenset([self._frame, other._frame]))
        cache = self.cacheable and other.cacheable

        return QueryInstance(
            lambda value: self(value) or other(value), frame, cache)

    def __invert__(self) -> QueryInstance:
        frame = ("not", self._frame)
        cache = self.cacheable
        return QueryInstance(lambda value: not self(value), frame, cache)

    def __bool__(self) -> NoReturn:
        raise NotImplementedError("QueryInstance cannot be used in boolean ")


class Query(QueryInstance):
    """
    TinyDB Queries.

    Allows building queries for TinyDB databases. There are two main ways of
    using queries:

    1) ORM-like usage:

    >>> User = Query()
    >>> await db.search(User.name == 'John Doe')
    >>> await db.search(User["logged-in"] == True)

    2) Classical usage:

    >>> await db.search(where("value") == True)

    Note that ``where(...)`` is a shorthand for ``Query(...)`` allowing for
    a more fluent syntax.

    Besides the methods documented here you can combine queries using the
    binary AND and OR operators:

    >>> # Binary AND:
    >>> await db.search((where("field1").exists()) & (where("field2") == 5))
    >>> # Binary OR:
    >>> await db.search((where("field1").exists()) | (where("field2") == 5))

    Queries are executed by calling the resulting object. They expect to get
    the document to test as the first argument and return ``True`` or
    ``False`` depending on whether the documents match the query or not.
    """

    def __init__(self) -> None:
        # The current path of fields to access when evaluating the object
        self._path: tuple[str | Callable, ...] = ()

        # Prevent empty queries to be evaluated
        def notest(_):
            raise RuntimeError("Empty query was evaluated")

        super().__init__(
            test=notest,
            frame=(None, (),),
            cacheable=True,
        )

    def __repr__(self):
        return f"{type(self).__name__}()"

    def __hash__(self):
        return super().__hash__()

    def __getattr__(self, item: str):
        if item.startswith("_"):
            warn("Don't construct Query by using attributes starting with `_`"
                 " as they are reserved for internal use. Use `[]` instead.",
                 UserWarning, 2)
        # A different syntax for ``__getitem__``

        return self.__getitem__(item)

    def __getitem__(self, item: str):
        # Generate a new query object with the new query path
        # We use type(self) to get the class of the current query in case
        # someone uses a subclass of ``Query``
        query = type(self)()

        # Now we add the accessed item to the query path ...
        query._path = (*self._path, item)

        # ... and update the query frame & cacheability
        query._frame = ("path", query._path)
        query._cacheable = self._cacheable

        return query

    def _generate_frame(self, op: str, value: Any) -> tuple[tuple, Any, bool]:
        """
        Try to freeze value and generate a frame for it.
        Otherwise return None as frame and the original value.
        **Assumes all hashable values are cacheable.**

        Returns a tuple of (frame, value, cacheablity).
        """
        if self.cacheable:
            with suppress(TypeError):
                value = freeze(value, True)
                return (op, self._path, value), value, True
        return (op, self._path, value), value, False

    def _generate_test(
            self,
            test: Callable[[Any], bool],
            frame: tuple,
            cacheable: bool = True,
            allow_empty_path: bool = False
    ) -> QueryInstance:
        """
        Generate a query based on a test function that first resolves the query
        path.

        :param test: The test the query executes.
        :param frame: The hash of the query.
        :return: A :class:`~asynctinydb.queries.QueryInstance` object
        """
        if not self._path and not allow_empty_path:
            raise ValueError("Query has no path")

        def runner(value):
            try:
                # Resolve the path
                for part in self._path:
                    if isinstance(part, str):
                        value = value[part]
                    else:
                        value = part(value)
            except (KeyError, TypeError):
                return False
            else:
                # Perform the specified test
                return test(value)

        return QueryInstance(
            runner,
            frame,
            self.cacheable and cacheable,
        )

    def __eq__(self, rhs: Any):
        """
        Test a dict value for equality.

        >>> Query().f1 == 42

        :param rhs: The value to compare against
        """

        frame, rhs, cache = self._generate_frame("==", rhs)
        return self._generate_test(lambda value: value == rhs, frame, cache)

    def __ne__(self, rhs: Any):
        """
        Test a dict value for inequality.

        >>> Query().f1 != 42

        :param rhs: The value to compare against
        """

        frame, rhs, cache = self._generate_frame("!=", rhs)
        return self._generate_test(lambda value: value != rhs, frame, cache)

    def __lt__(self, rhs: Any) -> QueryInstance:
        """
        Test a dict value for being lower than another value.

        >>> Query().f1 < 42

        :param rhs: The value to compare against
        """

        frame, rhs, cache = self._generate_frame("<", rhs)
        return self._generate_test(lambda value: value < rhs, frame, cache)

    def __le__(self, rhs: Any) -> QueryInstance:
        """
        Test a dict value for being lower than or equal to another value.

        >>> where("f1") <= 42

        :param rhs: The value to compare against
        """

        frame, rhs, cache = self._generate_frame("<=", rhs)
        return self._generate_test(lambda value: value <= rhs, frame, cache)

    def __gt__(self, rhs: Any) -> QueryInstance:
        """
        Test a dict value for being greater than another value.

        >>> Query().f1 > 42

        :param rhs: The value to compare against
        """

        frame, rhs, cache = self._generate_frame(">", rhs)
        return self._generate_test(lambda value: value > rhs, frame, cache)

    def __ge__(self, rhs: Any) -> QueryInstance:
        """
        Test a dict value for being greater than or equal to another value.

        >>> Query().f1 >= 42

        :param rhs: The value to compare against
        """

        frame, rhs, cache = self._generate_frame(">=", rhs)
        return self._generate_test(lambda value: value >= rhs, frame, cache)

    def exists(self) -> QueryInstance:
        """
        Test for a dict where a provided key exists.

        >>> Query().f1.exists()
        """
        return self._generate_test(lambda _: True, ("exists", self._path), True)

    def matches(self, regex: str | re.Pattern, flags: int = 0) -> QueryInstance:
        """
        Run a regex test against a dict value (whole string has to match).

        >>> Query().f1.matches(r"^\\w+$")

        :param regex: The regular expression to use for matching
        :param flags: regex flags to pass to ``re.match``
        """

        if isinstance(regex, str):
            regex = re.compile(regex, flags)

        def test(value: Any) -> bool:
            if not isinstance(value, str):
                return False

            return regex.match(value) is not None

        return self._generate_test(test, ("matches", self._path, regex), True)

    def search(self, regex: str | re.Pattern, flags: int = 0) -> QueryInstance:
        """
        Run a regex test against a dict value (only substring string has to
        match).

        >>> Query().f1.search(r"^\\w+$")

        :param regex: The regular expression to use for matching
        :param flags: regex flags to pass to ``re.match``
        """

        if isinstance(regex, str):
            regex = re.compile(regex, flags)

        def test(value: Any) -> bool:
            if not isinstance(value, str):
                return False

            return regex.search(value) is not None

        return self._generate_test(test, ("search", self._path, regex), True)

    def test(self, func: Callable[[Mapping], bool], *args, **kw) -> QueryInstance:
        """
        Run a user-defined test function against a dict value.

        >>> def test_func(val):
        ...     return val == 42
        ...
        >>> Query().f1.test(test_func)

        .. warning::

            The test function provided needs to be deterministic (returning the
            same value when provided with the same arguments), otherwise this
            may mess up the query cache that :class:`~tinydb.table.Table`
            implements.

        :param func: The function to call, passing the dict as the first
                     argument
        :param args: Additional arguments to pass to the test function
        """

        frame, (func, args, kw), cache = self._generate_frame("test", (func, args, kw))
        return self._generate_test(
            lambda value: func(value, *args, **kw), frame, cache)

    def any(self, cond: QueryLike | Container | Iterable) -> QueryInstance:
        """
        Check if a condition is met by any document in a list,
        where a condition can also be a sequence (e.g. list).

        >>> Query().f1.any(Query().f2 == 1)

        Matches::

            {"f1": [{"f2": 1}, {"f2": 0}]}

        >>> Query().f1.any([1, 2, 3])

        Matches::

            {"f1": [1, 2]}
            {"f1": [3, 4, 5]}

        :param cond: Either a query that at least one document has to match or
                     a list of which at least one document has to be contained
                     in the tested document.
        """

        frame: tuple = ("any", self._path, cond)
        if callable(cond):
            cache = is_cacheable(cond)

            def test(value):
                return is_iterable(value) and any(cond(e) for e in value)

        else:
            try:  # Try to speed up the test by using a set
                cond = frozenset(freeze(i, True) for i in cond)  # type: ignore
                frame = ("any", self._path, cond)
                cache = True

                def test(value):
                    if not is_iterable(value):
                        return False
                    for v in value:
                        with suppress(TypeError):
                            # Try to freeze the values to make them hashable
                            if freeze(v, True) in cond:  # pragma: no branch
                                return True
                    return False
            except TypeError:  # cond contains unhashable
                cache = False

                def test(value):
                    return is_iterable(value) and any(e in cond for e in value)

        return self._generate_test(test, frame, cache)

    def all(self, cond: QueryLike | Iterable[Any]) -> QueryInstance:
        """
        Check if a condition is met by all documents in a list,
        where a condition can also be a sequence (e.g. list).

        >>> Query().f1.all(Query().f2 == 1)

        Matches::

            {"f1": [{"f2": 1}, {"f2": 1}]}

        >>> Query().f1.all([1, 2, 3])

        Matches::

            {"f1": [1, 2, 3, 4, 5]}

        :param cond: Either a query that all documents have to match or a list
                     which has to be contained in the tested document.
        """

        frame: tuple = ("all", self._path, cond)
        if callable(cond):
            cache = is_cacheable(cond)

            def test(value):
                return is_iterable(value) and all(cond(e) for e in value)

        else:
            try:  # Try to speed up the test by using a set
                cond = frozenset(freeze(i, True) for i in cond)
                frame = ("all", self._path, cond)
                cache = True

                def test(value):
                    if not is_iterable(value):
                        return False

                    def _gen():
                        for v in value:
                            with suppress(TypeError):
                                # Skip unhashable values
                                yield freeze(v, True)
                    return cond.issubset(_gen())
            except TypeError:  # cond contains unhashable
                cache = False

                def test(value):
                    return supports_in(value) and all(e in value for e in cond)

        return self._generate_test(test, frame, cache)

    def one_of(self, items: Iterable | Container) -> QueryInstance:
        """
        Check if the value is contained in a list or generator.

        >>> Query().f1.one_of(['value 1', 'value 2'])

        :param items: The list of items to check with
        """

        try:
            items = frozenset(freeze(i, True) for i in items)  # type: ignore
            frame: tuple = ("one_of", self._path, items)
            cache = True

            def test(value):
                with suppress(TypeError):
                    return freeze(value) in items
                return False
        except TypeError:
            frame = ("one_of", self._path, items)
            cache = False

            def test(value):
                return value in items
        return self._generate_test(test, frame, cache)

    def fragment(self, document: Mapping) -> QueryInstance:
        frame, document, cache = self._generate_frame("fragment", document)

        def test(value: Any) -> bool:
            return all(k in value and value[k] == v
                       for k, v in document.items())

        return self._generate_test(
            test,
            frame,
            cacheable=cache,
            allow_empty_path=True
        )

    @staticmethod
    def noop() -> QueryInstance:
        """
        Always evaluate to ``True``.

        Useful for having a base value when composing queries dynamically.
        """

        return QueryInstance(
            lambda _: True,
            ("noop", ()),
            cacheable=True,
        )

    def map(self, fn: Callable[[Any], Any]) -> Query:
        """
        Add a function to the query path. Similar to __getattr__ but for
        arbitrary functions.
        """
        query = type(self)()

        # Now we add the callable to the query path ...
        query._path = (*self._path, fn)

        # ... and kill the hash - callable objects can be mutable, so it's
        # harmful to cache their results.
        query._frame = ("map", self._path, fn)
        query._cacheable = False

        return query


def where(key: str) -> Query:
    """
    A shorthand for ``Query()[key]``
    """
    return Query()[key]
