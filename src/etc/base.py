"""
Base Module template
"""


class BaseModule:
    """
    Base Module class
    """

    def __init__(self) -> None:
        self.name = "Base"
        self.description = "Base Module"
        self.supported_brokers: list[str] = []

    def options(self, context, module_options) -> None:  # pyright: ignore
        """
        Define module-specific arguments here.
        :param context:
        :param module_options:
        :return:
        """

    def on_login(self, context, connection) -> None:  # pyright: ignore
        """
        Called by Connection.call_modules() after login
        :param context:
        :param connection:
        :return:
        """

        raise NotImplementedError("Modules must implement on_login method.")
