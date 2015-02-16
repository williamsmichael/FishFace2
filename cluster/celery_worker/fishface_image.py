import numpy as np
import cv2
import cv2.cv as cv
import functools

NORMALIZED_SHAPE = (384, 512)
NORMALIZED_DTYPE = np.uint8


def ff_image_wrapper(func):
    @functools.wraps(func)
    def wrapper(ffimage, *args, **kwargs):
        fname = func.__name__
        ffimage.log = 'OP: {}'.format(fname)

        if not isinstance(ffimage, FFImage):
            raise TypeError('{} requires an FFImage object as its first argument.'.format(fname))

        ffimage.array = func(ffimage.array, *args, ffimage=ffimage, **kwargs)
        return ffimage

    return wrapper

def normalize(image):
    if image.shape == NORMALIZED_SHAPE:
        return image

    # too many color channels
    if len(image.shape) == 3:
        channels = image.shape[2]
        if channels == 3:
            conversion = cv.CV_BGR2GRAY
        elif channels == 4:
            conversion = cv.CV_BGRA2GRAY
        else:
            raise Exception("Why do I see {} color channels? ".format(channels) +
                            "I can only handle 1, 3, or 4 (with alpha).")

        image = cv2.cvtColor(image, conversion)

    if image.shape != NORMALIZED_SHAPE:
        image = cv2.resize(image,
                           dsize=tuple(reversed(NORMALIZED_SHAPE)),
                           interpolation=cv.CV_INTER_AREA)
    return image


class FFImage(object):
    def __init__(self, input_array=None, meta=None, log=None, normalize_image=True):
        if input_array is None:
            self.array = np.zeros(NORMALIZED_SHAPE, dtype=NORMALIZED_DTYPE)

        elif not isinstance(input_array, np.ndarray):
            raise InvalidSourceArray('If specified, input_array must be a numpy array.')

        elif not normalize_image and (input_array.shape != NORMALIZED_SHAPE or
                                      input_array.dtype != NORMALIZED_DTYPE):
            raise InvalidSourceArray('input_array must have shape {} and dtype {}.'.format(
                NORMALIZED_SHAPE, NORMALIZED_DTYPE))

        elif normalize_image:
            self.array = normalize(input_array)

        else:
            self.array = input_array

        self.meta = meta
        self._log = log

        if self.meta is None:
            self.meta = dict()

        if self._log is None:
            self._log = list()

    @property
    def log(self):
        return self._log

    @log.setter
    def log(self, item):
        self._log.append(item)

    @property
    def height(self):
        return self.array.shape[0]

    @property
    def width(self):
        return self.array.shape[1]


class InvalidSourceArray(Exception):
    pass