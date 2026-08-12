"""
runner.py: run the execution logic all together
"""

from argparse import Namespace
from concurrent.futures import Future, ThreadPoolExecutor, as_completed

from rich.progress import Progress, TaskID

from stonksmith.etc.console import stonksmith_console
from stonksmith.etc.context import BrokerDbProtocol, BrokerProtocol
from stonksmith.etc.logger import stonksmith_logger


def _collect(future: Future[bool | None]) -> bool:
    """
    Read one broker's outcome, turning a crash into a failed run.

    Typed ``Future[bool | None]`` rather than ``Future[bool]`` because None is
    a legitimate result: a broker under ~/.stonksmith/brokers may still declare
    ``broker_flow() -> None``, where None has always meant "finished". Narrowing
    it to bool would contradict the ``is not False`` test two lines down.

    ``future.result()`` was never called before, so anything escaping
    ``Connection.__call__`` vanished with the Future. That method catches
    everything ``broker_flow()`` raises, so this only fires for something
    outside it -- ``session.close()``, or a broker overriding ``__call__``.
    Re-raising would surface as a traceback out of ``asyncio.run()`` in main();
    the run has already failed, and one logged line plus a non-zero exit is
    more use to a scheduled job.
    :param future: A submitted broker call
    :return: False when the broker reported failure or the call raised
    :rtype: bool
    """

    try:
        return future.result() is not False

    except Exception as e:
        stonksmith_logger.exception(msg=f"Broker run failed: {e}")
        return False


async def start_run(
    broker_obj: BrokerProtocol, db: BrokerDbProtocol, args: Namespace
) -> bool:
    """
    Run StonkSmith execution logic
    :param broker_obj:
    :type broker_obj:
    :param db:
    :type db:
    :param args:
    :type args:
    :return: True when every broker reported it did its work
    :rtype: bool
    """

    stonksmith_logger.display(msg="Creating ThreadPoolExecutor")

    no_progress: bool = getattr(args, "no_progress", False)
    threads: int = getattr(args, "threads", 0)
    ok: bool = True

    if no_progress:
        with ThreadPoolExecutor(max_workers=threads + 1) as executor:
            stonksmith_logger.highlight(msg=f"Executing {broker_obj}")
            futures: list[Future[bool | None]] = [
                executor.submit(broker_obj, args, db, None)
            ]
            for future in as_completed(fs=futures):
                # Bound first: `ok = _collect(...) and ok` short-circuits once
                # ok is False, and a second broker would never be read.
                broker_ok: bool = _collect(future=future)
                ok = ok and broker_ok

    else:
        with (
            Progress(console=stonksmith_console) as progress,
            ThreadPoolExecutor(max_workers=threads + 1) as executor,
        ):
            task_id: TaskID = progress.add_task(
                description=f"[green]Running {broker_obj.name}",
                total=1,
            )
            futures = [executor.submit(broker_obj, args, db, None)]
            for future in as_completed(fs=futures):
                broker_ok = _collect(future=future)
                ok = ok and broker_ok
                progress.update(task_id=task_id, advance=1)

    return ok
