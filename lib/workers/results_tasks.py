import os
import datetime
import io
import collections

import pytz


os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'lib.django.django_fishface.settings')
import lib.django.djff.models as dm
import django.utils.timezone as dut
import django.shortcuts as ds
import django.core.files.base as dcfb

import celery
from lib.django_celery import celery_app

from lib.fishface_logging import logger, dense_log

@celery.shared_task(name='results.ping')
def ping():
    return True


@celery.shared_task(bind=True, name='results.debug_task')
def debug_task(self, *args, **kwargs):
    return '''
    Request: {0!r}
    Args: {1}
    KWArgs: {2}
    '''.format(self.request, args, kwargs)


@celery.shared_task(name='results.store_analyses')
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

        analysis.save()

        return analysis.id


@celery.shared_task(name='results.post_image')
def post_image(image_data, meta):
    xp_id = meta.get('xp_id', False)
    cjr_id = meta.get('cjr_id', 0)
    if not xp_id and cjr_id:
        xp_id = dm.CaptureJobRecord.objects.get(pk=meta['cjr_id']).xp_id
    elif not xp_id and not cjr_id:
        raise ImagePostError('Could not determine the experiment associated with the image.')
    xp = ds.get_object_or_404(dm.Experiment, pk=xp_id)

    image_config = dict()
    for key in 'cjr_id is_cal_image capture_timestamp voltage current'.split(' '):
        image_config[key] = meta[key]

    image_config['capture_timestamp'] = dut.datetime.utcfromtimestamp(
        float(image_config['capture_timestamp'])).replace(tzinfo=dut.utc)

    if image_config['is_cal_image']:
        image_config['cjr_id'] = None

    logger.debug(
        dense_log('', {
            'delta': round(meta.get('delta', 0), 3),
            'size': len(image_data),
            'requested_timestamp': meta.get('requested_timestamp', False),
            'capture_timestamp': meta.get('capture_timestamp', False),
        })
    )

    image = dm.Image(xp=xp, **image_config)
    image.image_file.save(image.image_file.name, dcfb.ContentFile(image_data))
    image.save()

    return {'id': image.id,
            'cjr_id': image.cjr_id,
            'xp_id': image.xp_id,
            'path': image.image_file.name}


@celery.shared_task(name='results.new_cjr')
def new_cjr(xp_id, voltage, current, start_timestamp):
    cjr = dm.CaptureJobRecord()

    cjr.xp_id = xp_id
    cjr.voltage = voltage
    cjr.current = current

    cjr.running = True

    cjr.job_start = datetime.datetime.utcfromtimestamp(
        float(start_timestamp)).replace(tzinfo=pytz.utc)

    cjr.save()

    return (start_timestamp, cjr.id)


@celery.shared_task(name='results.job_status_report')
def job_status_report(status, start_timestamp, stop_timestamp, voltage, current, seconds_left,
                      xp_id, cjr_id, species, total, remaining):
    if cjr_id is None:
        logger.debug('Still waiting for the CJR to be created for this job.')
        return

    cjr = ds.get_object_or_404(dm.CaptureJobRecord, pk=int(cjr_id))

    cjr.running = (status == "running")

    cjr.job_start = dut.datetime.utcfromtimestamp(float(start_timestamp)).replace(tzinfo=dut.utc)

    if stop_timestamp is not None:
        cjr.job_stop = dut.datetime.utcfromtimestamp(float(stop_timestamp)).replace(tzinfo=dut.utc)

    cjr.total = int(total)
    cjr.remaining = int(remaining)

    cjr.save()

    logger.info("Saved report for {}.".format(cjr.full_slug))

    return cjr.id


@celery.shared_task(name='results.power_supply_report')
def power_supply_log(timestamp, voltage_meas, current_meas, extra_report_data=None):
    psl = dm.PowerSupplyLog()
    psl.measurement_datetime = dut.datetime.utcfromtimestamp(
        float(timestamp)).replace(tzinfo=dut.utc)
    psl.voltage_meas = voltage_meas
    psl.current_meas = current_meas
    psl.save()

    return psl.id


@celery.shared_task(name='results.store_estimator')
def store_estimator(ml_combo_data):
    estimator_object = dm.KMeansEstimator()
    estimator_object.extract_and_store_details_from_estimator(ml_combo_data['estimator'])
    estimator_object.extract_and_store_details_from_scaler(ml_combo_data['scaler'])
    estimator_object.label_deltas = ml_combo_data['label_deltas']
    estimator_object.save()

    return estimator_object.id


@celery.shared_task(name='results.store_automatic_analysis_tags')
def store_automatic_analysis_tags(automatic_tags):
    for tag in automatic_tags:
        auto_tag = dm.AutomaticTag()
        auto_tag.image_analysis = dm.ImageAnalysis.objects.get(pk=tag['analysis_id'])
        auto_tag.image_id = auto_tag.image_analysis.image_id
        auto_tag.centroid = tag['centroid']
        auto_tag.orientation = tag['orientation']
        auto_tag.save()


@celery.shared_task(name='results.store_ellipse_search_tags')
def store_ellipse_search_tags(ellipse_tags):
    tag_ids = list()
    for tag in ellipse_tags:
        ellipse_tag = dm.EllipseSearchTag()
        ellipse_tag.image_id = tag['image_id']
        ellipse_tag.int_start = tag['start']
        ellipse_tag.int_end = tag['end']
        ellipse_tag.score = tag['score']
        ellipse_tag.save()
        tag_ids.append(ellipse_tag.id)

    return tag_ids


@celery.shared_task(name='results.update_cjr_ellipse_envelope')
def update_cjr_ellipse_envelope(args):
    tag_id, ellipse_size, color = args

    tag = dm.ManualTag.objects.get(pk=tag_id)
    cjr = tag.image.cjr

    major = max(ellipse_size)
    ratio = float(major) / min(ellipse_size)

    if cjr.major_max is None or major > cjr.major_max:
        cjr.major_max = major

    if cjr.major_min is None or major < cjr.major_min:
        cjr.major_min = major

    if cjr.color_max is None or color > cjr.color_max:
        cjr.color_max = color

    if cjr.color_min is None or color < cjr.color_min:
        cjr.color_min = min(color,1)

    if cjr.ratio_max is None or ratio > cjr.ratio_max:
        cjr.ratio_max = ratio

    if cjr.ratio_min is None or ratio < cjr.ratio_min:
        cjr.ratio_min = ratio

    cjr.save()


@celery.shared_task(name='results.update_multiple_envelopes', rate_limit='1/m')
def update_multiple_envelopes(envelope_data):
    cooked_envelopes = dict()

    cjrs = [dm.ManualTag.objects.get(pk=envelope_datum[0]).image.cjr for envelope_datum in envelope_data]

    for (tag_id, ellipse_size, new_color), cjr in zip(envelope_data, cjrs):
        env = cooked_envelopes.get(cjr.id, None)
        if env is None:
            env = cjr.search_envelope
            if env is None:
                # crazy set of values pretty much guaranteed to be overwritten by the rest of this task.
                env = {
                    'major_min': 100,
                    'major_max': 1,
                    'ratio_min': 10.0,
                    'ratio_max': 0.1,
                    'color_min': 255,
                    'color_max': 1,
                }
            env['cjr'] = cjr
            cooked_envelopes[cjr.id] = env

        new_major = max(ellipse_size)
        new_ratio = float(new_major) / min(ellipse_size)

        new_color = max(new_color, 1)

        if new_major < env['major_min']:
            env['major_min'] = new_major
        if new_major > env['major_max']:
            env['major_max'] = new_major

        if new_ratio < env['ratio_min']:
            env['ratio_min'] = new_ratio
        if new_ratio > env['ratio_max']:
            env['ratio_max'] = new_ratio

        if new_color < env['color_min']:
            env['color_min'] = new_color
        if new_color > env['color_max']:
            env['color_max'] = new_color

    for env in cooked_envelopes.itervalues():
        cjr = env['cjr']
        del env['cjr']
        for key, value in env.iteritems():
            setattr(cjr, key, value)
        cjr.save()



class AnalysisImportError(Exception):
    pass


class ImagePostError(Exception):
    pass