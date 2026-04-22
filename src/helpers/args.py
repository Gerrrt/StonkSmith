"""
args.py: Helpers for argument parser
"""

import inspect


def called_from_cmd_args():
    """
    Arguments passed from command line
    :return:
    :rtype:
    """
    for stack in inspect.stack():
        if stack[3] == "print_host_info":
            return True

        if (
            stack[3] == "plaintext_login"
            or stack[3] == "hash_login"
            or stack[3] == "kerberos_login"
        ):
            return True

        if stack[3] == "call_cmd_args":
            return True

    return False
