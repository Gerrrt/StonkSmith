#!/usr/bin/env python3
"""
Create database engine for stonksmith
"""

import cmd
import configparser
import csv
import os
import shutil
import sys
from os import listdir
from os.path import exists, join
from sqlite3 import connect
from textwrap import dedent

from etc.paths import config_path, workspace_dir, ws_path
from loaders.protocol import ProtocolLoader
from sqlalchemy import create_engine
from terminaltables import AsciiTable


class UserExitedProto(Exception):
    """
    Class to set up certain exceptions
    """
    pass


def create_db_engine(db_path):
    """
    Create database engine for stonksmith
    :param db_path:
    :return:
    """
    db_engine = create_engine(f"sqlite:///{db_path}",
                              isolation_level="AUTOCOMMIT", future=True)
    return db_engine


def print_table(data, title=None):
    """
    Print a table
    :param data: 
    :param title: 
    :return: 
    """
    print("")
    table = AsciiTable(data)
    if title:
        table.title = title
    print(table.table)
    print("")


def write_csv(filename, headers, entries):
    """
    Write entries to a csv file
    :param filename:
    :param headers:
    :param entries:
    :return:
    """
    with open(os.path.expanduser(filename), "w") as export_file:
        csv_file = csv.writer(
                export_file,
                delimiter=";",
                lineterminator="\n",
                escapechar="\\",
                )
        csv_file.writerow(headers)
        for entry in entries:
            csv_file.writerow(entry)


def write_list(filename, entries):
    """
    Write entries to a text file
    :param filename:
    :param entries:
    :return:
    """
    with open(os.path.expanduser(filename), "w") as export_file:
        for line in entries:
            export_file.write(line + "\n")
    return


def complete_import(text, line):
    """
    Tab-Complete 'import' commands
    :param text:
    :param line:
    :return:
    """
    commands = ("empire", "Metasploit")
    mline = line.partition(" ")[2]
    offs = len(mline) - len(text)
    return [s[offs:] for s in commands if s.startswith(mline)]


def complete_export(text, line):
    """
    Tab-Completion for stonksmithdb
    :param text:
    :param line:
    :return:
    """
    commands = (
        "creds",
        "plaintext",
        "hashes",
        "shares",
        "local_admins",
        "signing",
        "keys",
        )
    mline = line.partition(" ")[2]
    offs = len(mline) - len(text)
    return [s[offs:] for s in commands if s.startswith(mline)]


def print_help(help_string):
    """
    Print the help string
    :param help_string:
    """
    print(dedent(help_string))


class DatabaseNavigator(cmd.Cmd):
    """
    Implement the database navigator
    """
    def __init__(self, main_menu, database, proto):
        cmd.Cmd.__init__(self)
        self.main_menu = main_menu
        self.config = main_menu.config
        self.proto = proto
        self.db = database
        self.prompt = f"stonksmithdb ({main_menu.workspace})({proto}) > "
    
    def do_exit(self):
        """
        Shutdown stonksmithdb
        """
        self.db.shutdown_db()
        sys.exit()
    
    @staticmethod
    def help_exit():
        """
        Method to exit the help menu
        """
        help_string = """
        Exits
        """
        print_help(help_string)
    
    def do_back(self, line):
        """
        Go back to the main menu
        :param line: 
        """
        raise UserExitedProto
    
    def do_export(self, line):
        """
        Export stonksmithdb
        :param line: 
        :return: 
        """
        if not line:
            print("[-] not enough arguments")
            return
        line = line.split()
        command = line[0].lower()
        if command == "creds":
            if len(line) < 3:
                print("[-] invalid arguments, export creds "
                      "<simple|detailed|hashcat> <filename>")
                return

            filename = line[2]
            creds = self.db.get_credentials()
            csv_header = (
                "id",
                "domain",
                "username",
                "password",
                "credtype",
                "pillaged_from",
                )

            if line[1].lower() == "simple":
                write_csv(
                        filename, 
                        csv_header, 
                        creds)
            elif line[1].lower() == "detailed":
                formatted_creds = []

                for cred in creds:
                    entry = [
                        cred[0],
                        cred[1],
                        cred[2],
                        cred[3],
                        cred[4],
                        ]
                    if cred[5] is None:
                        entry.append("")
                    else:
                        entry.append(self.db.get_hosts(cred[5])[0][2])
                    formatted_creds.append(entry)
                write_csv(
                        filename, 
                        csv_header, 
                        formatted_creds)
            elif line[1].lower() == "hashcat":
                usernames = []
                passwords = []
                for cred in creds:
                    if cred[4] == "hash":
                        usernames.append(cred[2])
                        passwords.append(cred[3])
                output_list = [
                    ':'.join(combination) for combination in zip(
                        usernames,
                        passwords)]
                write_list(filename, output_list)
            else:
                print(f"[-] No such export option: {line[1]}")
                return
            print("[+] Creds exported")

    @staticmethod
    def help_export():
        """
        Export stonksmithdb
        """
        help_string = """
        export stuff
        """
        print_help(help_string)

    def do_import(self, line):
        """
        Import stonksmithdb
        :param line: 
        """
        pass


class STONKSMITHDBMenu(cmd.Cmd):
    """
    Initialize STONKSMITHDB menu
    """
    def __init__(self, local_config_path):
        """
        Initialize STONKSMITHDB menu
        """
        cmd.Cmd.__init__(self)
        self.local_config_path = local_config_path

        try:
            self.config = configparser.ConfigParser()
            self.config.read(self.local_config_path)
        except Exception as e:
            print(f"[-] Error reading stonksmith.conf: {e}")
            sys.exit(1)

        self.conn = None
        self.p_loader = ProtocolLoader()
        self.protocols = self.p_loader.get_protocols()

        self.workspace = self.config.get(
                "STONKSMITH",
                "workspace",)
        self.do_workspace(self.workspace)

        self.db = self.config.get(
                "STONKSMITH",
                "last_used_db",)
        if self.db:
            self.do_proto(self.db)

    def write_configfile(self):
        """
        Create config file
        """
        with open(self.local_config_path, "w") as configfile:
            self.config.write(configfile)

    def do_proto(self, proto):
        """
        Protocol
        :param proto:
        :return:
        """
        if not proto:
            return

        proto_db_path = join(
                workspace_dir, 
                self.workspace, 
                f"{proto}.db",)
        if exists(proto_db_path):
            self.conn = create_db_engine(proto_db_path)
            db_nav_object = self.p_loader.load_protocol(self.protocols[
                                                            proto]["nvpath"])
            db_object = self.p_loader.load_protocol(self.protocols[proto][
                                                        "dbpath"])
            self.config.set(
                    "STONKSMITH",
                    "last_used_db",
                    proto)
            self.write_configfile()
            try:
                proto_menu = getattr(
                        db_nav_object, 
                        "navigator")(
                        self,
                        getattr(
                                db_object, 
                                "database"
                                )(self.conn), 
                        proto)
                proto_menu.cmdloop()
            except UserExitedProto:
                pass 
            
    @staticmethod
    def help_proto():
        """
        Protocol menu
        """
        help_string = """
        proto [smb|mssql|winrm]
            *unimplemented protocols: ftp, rdp, ldap, ssh
        Changes stonksmithdb to the specified protocol
        """
        print_help(help_string)

    def do_workspace(self, line):
        """
        Workspace menu
        :param line:
        """
        line = line.strip()
        if not line:
            subcommand = ""
            self.help_workspace()
        else:
            subcommand = line.split()[0]

        if subcommand == "create":
            new_workspace = line.split()[1].strip()
            print(f"[*] Creating workspace '{new_workspace}'")
            self.create_workspace(
                    new_workspace,
                    self.p_loader,
                    self.protocols)
            self.do_workspace(new_workspace)
        elif subcommand == "list":
            print("[*] Enumerating Workspaces")
            for workspace in listdir(workspace_dir):
                if workspace == self.workspace:
                    print("==> " + workspace)
                else:
                    print(workspace)
        elif exists(join(workspace_dir, line)):
            self.config.set(
                    "STONKSMITH",
                    "workspace",
                    line)
            self.write_configfile()
            self.workspace = line
            self.prompt = f"stonksmithdb ({line}) > "

    @staticmethod
    def help_workspace():
        """
        Workspace help
        """
        help_string = """
        workspace [create <targetName> | workspace list | workspace 
        <targetName>]
        """
        print_help(help_string)

    @staticmethod
    def do_exit():
        """
        Exit STONKSMITHDB
        """
        sys.exit()

    @staticmethod
    def help_exit():
        """
        Exit stonksmithdb
        """
        help_string = """
        Exits 
        """
        print_help(help_string)

    @staticmethod
    def create_workspace(workspace_name, p_loader, protocols):
        """
        Create workspace
        :param workspace_name:
        :param p_loader:
        :param protocols:
        """
        os.mkdir(join(workspace_dir, workspace_name))

        for protocol in protocols.keys():
            protocol_object = p_loader.load_protocol(protocols[protocol][
                                                         "dbpath"])
            proto_db_path = join(workspace_dir, workspace_name,
                                 f"{protocol}.db")

            if not exists(proto_db_path):
                print(f"[*] Initializing {protocol.upper()} protocol database")
                conn = connect(proto_db_path)
                c = conn.cursor()

                c.execute("PRAGMA journal_mode = OFF")
                c.execute("PRAGMA foreign_keys = 1")

                getattr(protocol_object, "database").db_schema(c)

                conn.commit()
                conn.close()


def delete_workspace(workspace_name):
    """
    Delete workspace
    :param workspace_name:
    """
    shutil.rmtree(join(workspace_dir, workspace_name))


def initialize_db(logger):
    """
    Initialize the database
    :param logger:
    """
    if not exists(join(ws_path, "default")):
        logger.debug("Creating default workspace")
        os.mkdir(join(ws_path, "default"))
    
    p_loader = ProtocolLoader()
    protocols = p_loader.get_protocols()
    for protocol in protocols.keys():
        protocol_object = p_loader.load_protocol(protocols[protocol]["dbpath"])
        proto_db_path = join(ws_path, "default", f"{protocol}.db")

        if not exists(proto_db_path):
            logger.debug(f"Initializing {protocol.upper()} protocol database")
            conn = connect(proto_db_path)
            c = conn.cursor()
            c.execute("PRAGMA journal_mode = OFF")
            c.execute("PRAGMA foreign_keys = 1")
            c.execute("PRAGMA busy_timeout = 5000")
            getattr(protocol_object, "database").db_schema(c)
            conn.commit()
            conn.close()


def main():
    """
    Main function
    :return:
    """
    if not exists(config_path):
        print("[-] Unable to find config file")
        sys.exit(1)
    try:
        stonksmithdbnav = STONKSMITHDBMenu(config_path)
        stonksmithdbnav.cmdloop()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
