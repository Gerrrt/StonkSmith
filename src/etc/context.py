#!/usr/bin/env python3

import configparser
import os


class Context:
    def __init__(self, db, logger, args):
        for key, value in vars(args).items():
            setattr(self, key, value)

        self.db = db
        self.log_folder_path = os.path.join(
            os.path.expanduser("~/.stonksmith"),
            "logs",
        )
        self.localip = None

        self.conf = configparser.ConfigParser()
        self.conf.read(os.path.expanduser("~/.stonksmith/stonksmith.conf"))

        self.log = logger
