"""Awake being to life. Main start execution entry point."""
import asyncio
import os
import signal
import sys
import time
from typing import Optional

from being.backends import CanBackend
from being.being import Being
from being.clock import Clock
from being.config import CONFIG
from being.connectables import MessageInput
from being.logging import get_logger
from being.web.server import init_web_server, run_web_server
from being.web.web_socket import WebSocket


API_PREFIX = CONFIG['Web']['API_PREFIX']
WEB_SOCKET_ADDRESS = CONFIG['Web']['WEB_SOCKET_ADDRESS']
INTERVAL = CONFIG['General']['INTERVAL']
WEB_INTERVAL = CONFIG['Web']['INTERVAL']
LOGGER = get_logger(__name__)


def _signal_handler(signum=None, frame=None):
    """Signal handler for exit program."""
    #pylint: disable=unused-argument
    sys.exit(0)


def _run_being_standalone(being):
    """Run being standalone without web server / front-end."""
    if os.name == 'posix':
        signal.signal(signal.SIGTERM, _signal_handler)

    while True:
        now = time.perf_counter()
        being.single_cycle()
        then = time.perf_counter()
        time.sleep(max(0, INTERVAL - (then - now)))


async def _run_being_async(being):
    """Run being inside async loop."""
    time_func = asyncio.get_running_loop().time
    while True:
        now = time_func()
        being.single_cycle()
        then = time_func()
        await asyncio.sleep(max(0, INTERVAL - (then - now)))


async def _send_being_state_to_front_end(being: Being, ws: WebSocket):
    """Keep capturing the current being state and send it to the front-end.
    Taken out from ex being._run_web() because web socket send might block being
    main loop.

    Args:
        being: Being instance.
        ws: Active web socket.
    """
    dummies = []
    for out in being.messageOutputs:
        dummy = MessageInput(owner=None)
        out.connect(dummy)
        dummies.append(dummy)


    while True:
        await ws.send_json({
            'type': 'being-state',
            'timestamp': being.clock.now(),
            'values': [out.value for out in being.valueOutputs],
            'messages': [
                list(dummy.receive())
                for dummy in dummies
            ],
        })
        await asyncio.sleep(WEB_INTERVAL)


async def _run_being_with_web_server(being):
    """Run being with web server. Continuation for awake() for asyncio part.

    Args:
        being: Being instance.
    """
    if os.name == 'posix':
        loop = asyncio.get_running_loop()
        loop.add_signal_handler(signal.SIGTERM, _signal_handler)

    ws = WebSocket()
    app = init_web_server(being, ws)
    await asyncio.gather(
        _run_being_async(being),
        _send_being_state_to_front_end(being, ws),
        run_web_server(app),
        ws.run_broker(),
    )


def awake(*blocks,
        web: bool = True,
        clock: Optional[Clock] = None,
        network: Optional[CanBackend] = None,
    ):
    """Run being block network.

    Args:
        blocks: Some blocks of the network.

    Kwargs:
        web: Run with web server.
        clock: Clock instance.
        network: CanBackend instance.
    """
    if clock is None:
        clock = Clock.single_instance_setdefault()

    if network is None:
        network = CanBackend.single_instance_get()

    being = Being(blocks, clock, network)

    for motor in being.motors:
        motor.home()
        motor.enable()

    try:
        if web:
            asyncio.run(_run_being_with_web_server(being))
        else:
            _run_being_standalone(being)

    except Exception as err:
        LOGGER.fatal(err, exc_info=True)
        # TODO(atheler): Log and throw anti pattern. Want to see error in stderr
        # as well.
        raise