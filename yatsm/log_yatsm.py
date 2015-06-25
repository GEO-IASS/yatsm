import logging

_FORMAT = '%(asctime)s:%(levelname)s:%(module)s.%(funcName)s:%(message)s'
_formatter = logging.Formatter(_FORMAT)
_handler = logging.StreamHandler()
_handler.setFormatter(_formatter)

logger = logging.getLogger('yatsm')
logger.addHandler(_handler)
logger.setLevel(logging.INFO)
