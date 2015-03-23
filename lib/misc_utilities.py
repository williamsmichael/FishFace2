import time
import logging
import os


def delay_until(unix_timestamp):
    now = time.time()
    while now < unix_timestamp:
        time.sleep(unix_timestamp - now)
        now = time.time()


def delay_for_seconds(seconds):
    later = time.time() + seconds
    delay_until(later)


class AttrDict(dict):
    def __init__(self, *args, **kwargs):
        super(AttrDict, self).__init__(*args, **kwargs)
        self.__dict__ = self


def return_text_file_contents(file_path, strip=True, ignore_fail=True):
    try:
        with open(file_path, 'rt') as f:
            if strip:
                return f.read().strip()
            else:
                return f.read()
    except IOError:
        if not ignore_fail:
            logging.warning("Couldn't read file: {}".format(file_path))
        return ''

def chunkify(chunkable, chunk_length=1):
    while chunkable:
        chunk = chunkable[:chunk_length]
        chunkable = chunkable[chunk_length:]
        yield chunk

def is_file(*args):
    return os.path.isfile(os.path.join(*args))