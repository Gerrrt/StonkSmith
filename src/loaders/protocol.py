#!/usr/bin/env python3

"""
Load assistant
"""

from importlib.machinery import SourceFileLoader
from os import listdir
from os.path import dirname, exists, expanduser, join
from types import ModuleType

import src


class ProtocolLoader:
    """
    Load assistant protocols
    """
    def __init__(self):
        self.stonksmith_path = expanduser("~/.stonksmith")
    
    @staticmethod
    def load_protocol(protocol_path):
        """
        Load a protocol
        :param protocol_path: 
        :return: 
        """
        loader = SourceFileLoader(
                "protocol", 
                protocol_path)
        protocol = ModuleType(loader.name)
        loader.exec_module(protocol)
        return protocol
    
    def get_protocols(self):
        """
        Gather all protocols
        :return: 
        """
        protocols = {}
        protocol_paths = [
            join(dirname(src.__file__), "protocols"),
            join(self.stonksmith_path, "protocols"),
            ]
        
        for path in protocol_paths:
            for protocol in listdir(path):
                if protocol[-3:] == ".py" and protocol[:-3] != "__init__":
                    protocol_path = join(path, protocol)
                    protocol_name = protocol[:-3]
                    
                    protocols[protocol_name] = {"path": protocol_path}
                    
                    db_file_path = join(
                            path, 
                            protocol_name, 
                            "database.py")
                    db_nav_path = join(
                            path, 
                            protocol_name, 
                            "db_navigator.py")
                    protocol_args_path = join(
                            path, 
                            protocol_name,
                            "proto_args.py")
                    if exists(db_file_path):
                        protocols[protocol_name]["dbpath"] = db_file_path
                    if exists(db_nav_path):
                        protocols[protocol_name]["nvpath"] = db_nav_path
                    if exists(protocol_args_path):
                        protocols[protocol_name]["argspath"] = (
                            protocol_args_path)
        
        return protocols
