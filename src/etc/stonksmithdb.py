#!/usr/bin/env python3
"""
Create database engine for stonksmith
"""

from os.path import exists

from etc.paths import config_path


def main():
    if not exists(config_path):
        print("[-] Unable to find config file")
        sys.exit(1)
    try:
        stonksmithdbnav = STONKSMITHDBMenu(config_path)
        stonksmithdbnav.stonksmithloop()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
