"""
runner.py: run the execution logic all together
"""

from argparse import Namespace
from concurrent.futures import ThreadPoolExecutor, as_completed
from concurrent.futures._base import Future
from typing import Any

from rich.progress import Progress, TaskID

from etc.console import stonksmith_console
from etc.context import BrokerDbProtocol
from etc.logger import stonksmith_logger


async def start_run(broker_obj: Any, db: BrokerDbProtocol, args: Namespace) -> None:
    """
    Run StonkSmith execution logic
    :param broker_obj:
    :type broker_obj:
    :param db:
    :type db:
    :param args:
    :type args:
    :return:
    :rtype:
    """

    stonksmith_logger.display(msg="Creating ThreadPoolExecutor")

    no_progress: bool = getattr(args, "no_progress", False)
    threads: int = getattr(args, "threads", 0)

    if no_progress:
        with ThreadPoolExecutor(max_workers=threads + 1) as executor:
            stonksmith_logger.highlight(msg=f"Executing {broker_obj}")
            futures: list[Future[None]] = [executor.submit(broker_obj, args, db, None)]
            for _ in as_completed(fs=futures):
                pass

    else:
        with Progress(console=stonksmith_console) as progress, ThreadPoolExecutor(
            max_workers=threads + 1
        ) as executor:
            task_id: TaskID = progress.add_task(
                description=f"[green]Running {broker_obj.name}",
                total=1,
            )
            futures = [executor.submit(broker_obj, args, db, None)]
            for _ in as_completed(fs=futures):
                progress.update(task_id=task_id, advance=1)
