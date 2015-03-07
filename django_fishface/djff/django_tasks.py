import os
import datetime
import random

import numpy as np

import celery

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'django_fishface.settings')
from django.conf import settings
import models as dm
import django.utils.timezone as dut
import django.db.models as ddm
import django.shortcuts as ds

HOME = os.environ['HOME']
ALT_ROOT = HOME

from fishface_image import FFImage
from fishface_celery import app as celery_app


# used for testing
@celery.shared_task(name='django.return_passthrough')
def return_passthrough(*args, **kwargs):
    return {'args': args, 'kwargs': kwargs}


@celery.shared_task(name='django.analyze_cjr_images')
def analyze_cjr_images(cjr_ids):
    results = list()

    if not isinstance(cjr_ids, (list, tuple)):
        cjr_ids = [cjr_ids]

    for cjr_id in cjr_ids:
        cjr = dm.CaptureJobRecord.objects.get(pk=cjr_id)
        cal_image = FFImage(source_filename=cjr.cal_image.image_file.path,
                            store_source_image_as='jpg')
        cjr_data = dm.Image.objects.filter(cjr_id=cjr.id)
        ff_images = [
            FFImage(source_filename=datum.image_file.path,
                    meta={'image_id': datum.id})
            for datum in cjr_data
        ]

        for ff_image in ff_images:
            results.append(
                celery.chain(celery_app.signature('drone.get_fish_contour',
                                                  args=(ff_image, cal_image)),
                             celery_app.signature('django.store_analyses'),
                ).apply_async()
            )

    return results


@celery.shared_task(name='django.store_analyses')
def store_analyses(metas):
    # if we only have one meta, wrap it in a list
    if isinstance(metas, dict):
        metas = [metas]

    for meta in metas:
        # if we don't have an image ID in the metadata, there's not much use in proceeding
        try:
            image = dm.Image.objects.get(pk=int(meta['image_id']))
            del meta['image_id']
        except KeyError:
            raise AnalysisImportError('No image ID found in imported analysis metadata.')

        # remove the debugging and intermediate stuff that we don't need to keep
        for key in 'log all_contours'.split(' '):
            try:
                del meta[key]
            except KeyError:
                pass

        # translate the field names used during processing to the field names to store in the database
        analysis_config = {
            'analysis_datetime': 'timestamp',
            'silhouette': 'largest_contour',
            'hu_moments': 'hu_moments',
            'moments': 'moments',
        }
        for key, meta_key in analysis_config.iteritems():
            try:
                analysis_config[key] = meta[meta_key]
                del meta[meta_key]
            except KeyError:
                raise AnalysisImportError("Couldn't find '{}' in imported metadata.".format(meta_key))

            if 'ndarray' in str(analysis_config[key].__class__):
                analysis_config[key] = analysis_config[key].tolist()

            if key == 'hu_moments':
                analysis_config[key] = [x[0] for x in analysis_config[key]]

        analysis_config['analysis_datetime'] = datetime.datetime.utcfromtimestamp(
            float(analysis_config['analysis_datetime'])).replace(tzinfo=dut.utc)


        # whatever remains in the meta variable gets stored here
        analysis_config['meta_data'] = meta

        analysis = dm.ImageAnalysis(image=image, **analysis_config)

        return analysis.save()


@celery.shared_task(name='django.train_classifier')
def train_classifier(minimum_verifications=2, reserve_for_ml_verification=0.1):
    eligible_image_ids = frozenset([i.id for i in dm.Image.objects.annotate(
        analysis_count=ddm.Count('imageanalysis')
    ).filter(
        analysis_count__gte=1
    )])

    eligible_tags = random.shuffle(list(
        dm.ManualTag.objects.annotate(
            verify_count=ddm.Count('manualverification'),
        ).filter(
            verify_count__gte=minimum_verifications,
            image_id__in=eligible_image_ids
        )
    ))

    split_point = int(float(len(eligible_tags)) * reserve_for_ml_verification)

    verification_set, training_set = eligible_tags[:split_point], eligible_tags[split_point:]


@celery.shared_task(name='django.post_image')
def post_image(image_data, meta):
    xp = ds.get_object_or_404(dm.Experiment, pk=int(meta['xp_id']))

    image_config = dict()
    for key in 'cjr_id is_cal_image capture_timestamp voltage current'.split(' '):
        image_config[key] = meta[key]

    image = dm.Image(xp=xp, **image_config)
    image.image_file = image_data
    image.save()


class AnalysisImportError(Exception):
    pass