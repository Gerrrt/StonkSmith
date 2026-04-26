import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


class StonkSmithDBNavigationTests(unittest.TestCase):
    """Regression tests for StonkSmithDBMenu.do_broker.

    Ensures that the already-initialized Database instance is passed
    directly to DatabaseNavigator, rather than being re-invoked as a
    callable (the previous bug: nav_class(self, db_instance(engine), broker)).
    """

    @patch("etc.stonksmithdb.create_db_engine")
    def test_do_broker_passes_db_instance_to_navigator(
        self,
        mock_create_engine: MagicMock,
    ) -> None:
        from etc.stonksmithdb import StonkSmithDBMenu

        mock_engine = MagicMock()
        mock_create_engine.return_value: MagicMock = mock_engine

        # The pre-initialized DB instance that should be handed to the navigator.
        db_instance = MagicMock()

        # Capture what the navigator constructor receives as its second argument.
        captured: list[object] = []

        class FakeNavigator:
            def __init__(self, parent: object, db: object, broker: str) -> None:
                captured.append(db)

            def cmdloop(self) -> None:
                pass

        db_mod = SimpleNamespace(Database=MagicMock(return_value=db_instance))
        nav_mod = SimpleNamespace(DatabaseNavigator=FakeNavigator)

        broker_name = "schwab529plan"

        # Build a bare StonkSmithDBMenu instance without calling __init__.
        menu = StonkSmithDBMenu.__new__(StonkSmithDBMenu)
        menu.workspace = "default"
        menu.config = MagicMock()
        menu.write_config = MagicMock()
        menu.brokers = {
            broker_name: {
                "nvpath": "fake/nav",
                "dbpath": "fake/db",
            },
        }
        # Wire broker_loader.load_broker to return nav_mod then db_mod.
        menu.broker_loader = MagicMock()
        menu.broker_loader.load_broker.side_effect = [nav_mod, db_mod]

        # Make the db_file path appear to exist.
        fake_db_file = MagicMock(spec=Path)
        fake_db_file.__truediv__ = MagicMock(return_value=fake_db_file)
        fake_db_file.exists.return_value = True

        with patch("etc.stonksmithdb.Path", return_value=fake_db_file):
            menu.do_broker(broker=broker_name)

        self.assertEqual(
            len(captured),
            1,
            "Navigator should have been instantiated once",
        )
        self.assertIs(
            captured[0],
            db_instance,
            "Navigator must receive the DB instance directly, not a callable re-invocation",
        )
        # Confirm db_instance was never called as a constructor.
        db_instance.assert_not_called()


if __name__ == "__main__":
    unittest.main()


if __name__ == "__main__":
    unittest.main()
