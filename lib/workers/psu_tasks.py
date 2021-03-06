import os
import time

import celery
import redis

from lib.fishface_celery import celery_app
from lib.fishface_logging import logger

import etc.fishface_config as ff_conf

if ff_conf.REAL_POWER_SUPPLY:
    logger.info('Running with real power supply.')
    from lib.RobustPowerSupply import RobustPowerSupply as psu_class
else:
    logger.warning('Running with fake power supply.')
    from lib.FakeHardware import HP6652a as psu_class


@celery.shared_task(name='psu.ping')
def ping():
    return True


@celery.shared_task(bind=True, name='psu.debug_task')
def debug_task(self, *args, **kwargs):
    return '''
    Request: {0!r}
    Args: {1}
    KWArgs: {2}
    '''.format(self.request, args, kwargs)


class PSUTask(celery.Task):
    abstract = True
    _power_supply = {'psu': None}
    _redis_client = redis.Redis(
        host=ff_conf.REDIS_HOSTNAME,
        password=ff_conf.REDIS_PASSWORD
    )

    @property
    def power_supply(self):
        if self._power_supply['psu'] is None:
            self._power_supply['psu'] = PowerSupply()
            self._power_supply['psu'].open()
        return self._power_supply['psu']


class PowerSupply(object):
    def __init__(self):
        self.voltage = None
        self.current = None
        self.output = None
        self.psu = None

    def open(self):
        if self.psu is not None:
            return False

        self.psu = psu_class()
        self.voltage = self.psu.voltage
        self.current = self.psu.current
        self.output = self.psu.output

        return True

    def close(self):
        if self.psu is None:
            return False

        self.voltage = None
        self.current = None
        self.output = None
        self.psu = None

        return True

    def reset(self):
        self.set_psu(reset=True)

    def set_psu(self, voltage=False, current=False, output=False, reset=False):
        if self.psu is None:
            return False

        if reset:
            voltage = 0
            current = 0
            output = False
            self.psu.reset()

        if voltage:
            logger.info("setting psu voltage to {} V".format(
                voltage
            ))
            self.psu.voltage = voltage
        else:
            self.psu.voltage = 0

        if current:
            logger.info("setting psu max current to {} A".format(
                current
            ))
            self.psu.current = current
        else:
            self.psu.current = 0

        if output:
            logger.info("enabling psu output")
        else:
            logger.info("disabling psu output")

        self.psu.output = output

        return self.report()

    def report(self, extra_report_data=None, post=True):
        if self.psu is None:
            return False
        else:
            state = {
                'timestamp': time.time(),
                'current_meas': self.psu.current_sense,
                'voltage_meas': self.psu.voltage_sense,
            }

        if extra_report_data is not None:
            state['extra_report_data'] = extra_report_data

        if post:
            celery_app.send_task('results.power_supply_report', kwargs=state)

        return state


@celery.shared_task(base=PSUTask, name="psu.set_psu")
def set_psu(*args, **kwargs):
    return set_psu.power_supply.set_psu(*args, **kwargs)


@celery.shared_task(base=PSUTask, name='psu.reset_psu')
def reset_psu():
    set_psu.power_supply.set_psu(reset=True)


@celery.shared_task(base=PSUTask, name="psu.report")
def report(extra_report_data=None):
    report_ = report.power_supply.report(extra_report_data)
    report._redis_client.set('ff_cache_power_supply', report_)
    return report_


@celery.shared_task(base=PSUTask, name="psu.cached_report")
def cached_report():
    return cached_report._redis_client.get('ff_cache_power_supply')


class PowerSupplyError(Exception):
    pass