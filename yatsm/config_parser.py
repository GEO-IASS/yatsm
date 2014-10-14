try:
    import ConfigParser as configparser
except ImportError:
    import configparser

import numpy as np


# CONFIG FILE PARSING
def _parse_config_v_zero_pt_one(config_file):
    """ Parses config file for version 0.1.x """
    # Defaults
    defaults = {
        'date_format': '%Y%j',
        'output_prefix': 'yatsm_r',
        'use_bip_reader': False,
        'training_image': None
    }

    config = configparser.ConfigParser(defaults=defaults, allow_no_value=True)
    config.read(config_file)

    # Configuration for dataset
    dataset_config = dict.fromkeys(['input_file', 'date_format',
                                    'output', 'output_prefix',
                                    'training_image',
                                    'n_bands', 'mask_band',
                                    'green_band', 'swir1_band',
                                    'use_bip_reader'])
    for k in dataset_config:
        dataset_config[k] = config.get('dataset', k)

    if dataset_config['training_image'] == 'None':
        dataset_config['training_image'] = None
    dataset_config['n_bands'] = int(dataset_config['n_bands'])
    dataset_config['mask_band'] = int(dataset_config['mask_band']) - 1
    dataset_config['green_band'] = int(dataset_config['green_band']) - 1
    dataset_config['swir1_band'] = int(dataset_config['swir1_band']) - 1

    # Configuration for YATSM algorithm
    yatsm_config = {}

    yatsm_config['consecutive'] = int(config.get('YATSM', 'consecutive'))
    yatsm_config['threshold'] = float(config.get('YATSM', 'threshold'))
    yatsm_config['min_obs'] = int(config.get('YATSM', 'min_obs'))
    yatsm_config['min_rmse'] = float(config.get('YATSM', 'min_rmse'))
    yatsm_config['freq'] = config.get(
        'YATSM', 'freq').replace(',', ' ').split(' ')
    yatsm_config['freq'] = [int(v) for v in yatsm_config['freq']
                            if v != '']
    yatsm_config['test_indices'] = config.get(
        'YATSM', 'test_indices').replace(',', ' ').split(' ')
    yatsm_config['test_indices'] = np.array([int(b) for b in
                                             yatsm_config['test_indices']
                                             if b != ''])
    yatsm_config['screening'] = config.get('YATSM', 'screening')
    yatsm_config['lassocv'] = config.get('YATSM', 'lassocv').lower() == 'true'
    yatsm_config['reverse'] = config.get('YATSM', 'reverse').lower() == 'true'
    yatsm_config['robust'] = config.get('YATSM', 'robust').lower() == 'true'

    return (dataset_config, yatsm_config)


def parse_config_file(config_file):
    """ Parses config file into dictionary of attributes """

    config = configparser.ConfigParser()
    config.read(config_file)

    dataset_config = None
    yatsm_config = None

    # Parse different versions
    version = config.get('metadata', 'version').split('.')

    # 0.1.x
    if version[0] == '0' and version[1] == '1':
        dataset_config, yatsm_config = _parse_config_v_zero_pt_one(config_file)

    return (dataset_config, yatsm_config)
