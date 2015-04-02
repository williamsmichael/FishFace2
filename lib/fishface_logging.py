import os
import logging
import json

logger = logging.getLogger('fishface')
logger.setLevel(logging.DEBUG)

formatter = logging.Formatter('%(asctime)s %(levelname)s %(message)s')

LOG_TO_CONSOLE = True
CONSOLE_LOG_LEVEL = logging.INFO
FILE_LOG_LEVEL = logging.DEBUG
LOG_FILE_PATH = os.path.join(os.path.expanduser('~'), 'var', 'log', 'fishface.log')

console_handler = logging.StreamHandler()
console_handler.setLevel(CONSOLE_LOG_LEVEL)
console_handler.setFormatter(formatter)


file_handler = logging.FileHandler(LOG_FILE_PATH)
file_handler.setLevel(FILE_LOG_LEVEL)
file_handler.setFormatter(formatter)

logger.addHandler(file_handler)
if LOG_TO_CONSOLE:
    logger.addHandler(console_handler)


def dense_log(tag, dict_to_log):
    return 'DENSE_LOG#' + str(tag) + '#' + json.dumps(
        dict_to_log,
        separators=(',', ':'),
    )
