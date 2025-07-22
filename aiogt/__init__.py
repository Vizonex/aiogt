"""
aiogt
-----------
A graceful timeout timer unlike `async_timeout` and `asyncio.timeout()`
aiogt is made for helping implement a graceful exit in a given amount of time 
without an exceptions having to be thrown. 

This way actual aggressive timers will not have their errors being suppressed
if a timeout didn't make it and can be utilized as a safer version of
`asyncio.create_task(asyncio.sleep(...))`


best practices with graceful timeouts over aggressive timeouts.

-   Graceful Timeouts should be done either alone or before an aggressive timeout is being
    introducded. The reason is that if an aggressive timeout such as `async_timeout.timeout()` 
    or `asyncio.timeout()` is introduced before graceful timeout is used know that the 
    aggressive timeout has the ability to take over and may not allow you to safely cleanup 
    afterwards. 

-   Try to avoid using graceful timers for things that users might be impaitient about
    these items may include
    - impaitient networking (or webscraping)
    - things that need to be taken care of instantly rather than paitiendly.

-   Use graceful timeouts when things requires sensetive operations such as 
    - unshielded sql operations
    - networking that is allowed to wait as long as it needs for something to finish
    - benchmarking the performance of other asynchronous python libaries to see how many
    times a function or group of operations can complete in.
    - items that are unprotected by a context manager
    - sensetive exiting
    - you need to avoid suppressing errors like `asyncio.TimeoutError`
    - Evading Server's Rate-Limits while not exhausing the Server's resources or triggering DDOS attacks

"""

import asyncio
from enum import IntEnum
from types import TracebackType, coroutine
from typing import Optional, Type, final


__all__ = ("graceful_timeout", "graceful_timeout_at", "GracefulTimeout")

def graceful_timeout(delay:Optional[float]) -> "GracefulTimeout":
    """timeout context manager.

    Same as asyncio.timeout() but useful in cases where you want to leave
    a task gracefully instead of cancelling with an error thrown immediately.

    >>> async with graceful_timeout(10) as g:
    ...     while await g.is_running():
    ...         # run this multiple times within a 10 second period
    ...         # if timer reaches it's deadline the while loop will 
    ...         # safely exit this repeated task. 
    ...         async with aiohttp.get("https://httpbin.org/...") as r:
    ...             await r.text()

    waiting on a graceful timer is also allowed but remember to check the
    graceful timer to see when it finishes or wait on it otherwise it will 
    throw a `RuntimError` asking for you to do so because otherwise it 
    serves no purpose which is a bad thing.

    >>> async with graceful_timeout(10) as g:
    ...     async with aiohttp.get("https://httpbin.org/...") as r:
    ...         await r.text()
    ...     # Hope for a `RuntimeError` on exit...

    The correct way to do such a thing is to wait upon it afterwards if not in a while loop.

    >>> async with graceful_timeout(10) as g:
    ...     async with aiohttp.get("https://httpbin.org/...") as r:
    ...         await r.text()
    ...     # Wait for enough time to pass by before running again 
    ...     # We can avoid triggering server ratelimits this way
    ...     # keeping the both the server and client happy.
    ...     await g.wait()
    """
    
    loop = asyncio.get_event_loop()
    if delay is not None:
        deadline = loop.time() + delay
    else:
        deadline = None
    return GracefulTimeout(deadline, loop=loop)


def graceful_timeout_at(deadline: Optional[float]) -> "GracefulTimeout":
    """Schedule the timeout at absolute time.

    deadline argument points on the time in the same clock system
    as loop.time().

    Please note: it is not POSIX time but a time with
    undefined starting base, e.g. the time of the system power on.

    >>> async with graceful_timeout_at(loop.time() + 10) as g:
    ...     while await g.is_running():
    ...         # run this multiple times within a 10 second period
    ...         # if timer reaches it's deadline the while loop will 
    ...         # safely exit this repeated task. 
    ...         async with aiohttp.get("https://httpbin.org/...") as r:
    ...             await r.text()

    """
    return GracefulTimeout(deadline, asyncio.get_running_loop())


@coroutine
def _s_heartbeat():
    """
    Allows a single cycle from the event loop
    to pass by it is equivilent to setting
    asyncio.sleep(0) but simpler and faster
    """
    yield


# I'll stick to what was implemented
# but I wanted to add a better system
# and int-enums seemed to be a better option.
class _State(IntEnum):
    INIT = 0
    ENTER = 1
    TIMEOUT = 2
    EXIT = 3


@final
class GracefulTimeout:
    """
    Graceful Timer allows things to be ran while inside of a while-loop
    and is allowed to be exited gracefully
    example::

        async with graceful_timeout(5) as gtimer:
            while await gtimer.is_running():
                ...
            # Somewhere after this while loop you
            # could perform something such as sensetive 
            # object cleanup.
    """

    __slots__ = ("_deadline", "_loop", "_state", "_timeout_handler", "_event", "_checked")

    def __init__(
        self, deadline: Optional[float], loop: asyncio.AbstractEventLoop
    ) -> None:
        self._loop = loop
        self._state = _State.INIT
        self._event = asyncio.Event()
        self._checked = False
        self._timeout_handler = None  # type: Optional[asyncio.Handle]
        if deadline is None:
            self._deadline = None  # type: Optional[float]
        else:
            self.update(deadline)

    async def wait(self):
        """Waits for the timer to complete this will wait until the timer finishes"""
        self._checked = True
        return await self._event.wait()

    async def is_running(self):
        """
        Checks to see if the timer is still active 
        this will wait a single cycle from the eventloop to 
        ensure that if only synchronous things are going on
        the evenloop cannot be held hostage by something else.
        """
        await _s_heartbeat()
        return not self._state != _State.TIMEOUT
    
    def _reject(self) -> None:
        if self._timeout_handler is not None:
            self._timeout_handler.cancel()
            self._timeout_handler = None

    def _do_exit(self, exc_type: Optional[Type[BaseException]]) -> None:
        if exc_type is asyncio.CancelledError and self._state == _State.TIMEOUT:
            self._timeout_handler = None
        
        if not self._checked:
            raise RuntimeError(f"graceful timers should always be checked or waited upon {self!r}")

        # timeout did not expire
        self._state = _State.EXIT
        self._reject()
        return None

    def _do_enter(self) -> None:
        if self._state != _State.INIT:
            raise RuntimeError(f"invalid state {self._state.value}")
        self._state = _State.ENTER
        self._reschedule()

    def update(self, deadline: float) -> None:
        """Set deadline to absolute value.

        deadline argument points on the time in the same clock system
        as loop.time().

        If new deadline is in the past the timer will set it's interal
        value to allow for a while-loop to be safely exited from.

        Please note: it is not POSIX time but a time with
        undefined starting base, e.g. the time of the system power on.
        """
        if self._state == _State.EXIT:
            raise RuntimeError("cannot reschedule after exit from context manager")
        if self._state == _State.TIMEOUT:
            raise RuntimeError("cannot reschedule expired timeout")
        if self._timeout_handler is not None:
            self._timeout_handler.cancel()
        self._deadline = deadline
        if self._state != _State.INIT:
            self._reschedule()

    def shift(self, delay: float) -> None:
        """Advance timeout on delay seconds.

        The delay can be negative.

        Raise RuntimeError if shift is called when 
        deadline is not scheduled
        """
        deadline = self._deadline
        if deadline is None:
            raise RuntimeError("cannot shift timeout if deadline is not scheduled")
        self.update(deadline + delay)

    def _reschedule(self) -> None:
        assert self._state == _State.ENTER
        deadline = self._deadline
        if deadline is None:
            return

        now = self._loop.time()
        if self._timeout_handler is not None:
            self._timeout_handler.cancel()

        if deadline <= now:
            self._timeout_handler = self._loop.call_soon(self._on_timeout)
        else:
            self._timeout_handler = self._loop.call_at(deadline, self._on_timeout)

    def _on_timeout(self) -> None:
        self._state = _State.TIMEOUT
        self._event.set()
        # drop the reference early
        self._timeout_handler = None
    
    async def __aenter__(self) -> "GracefulTimeout":
        self._do_enter()
        return self

    async def __aexit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc_val: Optional[BaseException],
        exc_tb: Optional[TracebackType],
    ) -> Optional[bool]:
        self._do_exit(exc_type)
        return None
    
