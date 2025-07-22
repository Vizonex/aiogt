# aiogt
A graceful timeout timer unlike `async_timeout` and `asyncio.timeout()`
aiogt is made for helping implement a graceful exit in a given amount of time 
without an exceptions having to be thrown. 

This way actual aggressive timers will not have their errors being suppressed
if a timeout didn't make it and can be utilized as a safer version of
`asyncio.create_task(asyncio.sleep(...))`


## Best Practices with Graceful Timeouts over Aggressive Timeouts.

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
