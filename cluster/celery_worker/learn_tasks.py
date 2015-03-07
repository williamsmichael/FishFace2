import os
import time

import sklearn
import sklearn.preprocessing as skp
import sklearn.cluster as skc

import celery
import fishface_celery


celery_app = fishface_celery.app

HOME = os.path.expanduser('~')
ALT_ROOT = HOME


@celery.shared_task(name="learn.cluster_hu_moments")
def cluster_hu_moments(hu_moments, n_clusters=40, n_init=10, init='k-means++'):
    try:
        if len(hu_moments[0]) != 7:
            raise ClusteringError("Hu moments contain 7 elements - the passed object doesn't fit" +
                                  "that criteria.")
    except IndexError:
        raise ClusteringError("Could not index to the 0th element of passed hu_moments.")

    data = skp.scale(hu_moments)
    estimator = skc.KMeans(init=init, n_clusters=n_clusters, n_init=n_init)

    predictions = estimator.fit_predict(data)

    return predictions, estimator


class ClusteringError(Exception):
    pass