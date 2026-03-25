"""
Module to clean up scraped data from https://www.schwab529plan.com
"""


def clean_up(data):
    """
    Clean up scraped data from https://www.schwab529plan.com.
    :param: data
    :return: data
    """
    if isinstance(data, str):
        return data.strip()
    if isinstance(data, list):
        return [clean_up(item) for item in data]
    if isinstance(data, dict):
        new_dict = {}
        for key, value in data.items():
            new_key = key.strip()
            new_value = clean_up(value)
            new_dict[new_key] = new_value
        return new_dict
    return data
