#!/usr/bin/env python3

"""
Module to load modules
"""

import src


class ModuleLoader:
    """
    Loads modules
    """

    def __init__(self, args, db, logger):
        self.args = args
        self.db = db
        self.logger = logger

    def module_is_sane(self, module, module_path):
        """
        Check for all required attributes
        :param module:
        :param module_path:
        :return:
        """

    def load_module(self, module_path):
        """
        Load module
        :param module_path:
        :return:
        """
