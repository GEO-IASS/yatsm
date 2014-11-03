""" Plots useful for YATSM
"""

import matplotlib.pyplot as plt
import numpy as np


def plot_feature_importance(algo, dataset_config, yatsm_config):
    """ Plots Random Forest feature importance as barplot

    Args:
      algo (sklearn.ensemble.RandomForestClassifier): Random Forest algorithm
      dataset_config (dict): dataset configuration details
      yatsm_config (dict): YATSM model run details

    """
    ind = np.arange(algo.feature_importances_.size)
    width = 0.5

    betas = range(0, 2 + 2 * len(yatsm_config['freq']))
    bands = range(1, dataset_config['n_bands'] + 1)
    bands.remove(dataset_config['mask_band'] + 1)  # band is now index so + 1

    names = [r'$Band {b} \beta_{i}$'.format(b=b, i=i)
             for i in betas for b in bands]
    names += [r'$Band {b} RMSE_{i}$'.format(b=b, i=i)
              for i in betas for b in bands]

    fig, ax = plt.subplots()
    ax.bar(ind, algo.feature_importances_, width)
    ax.set_xticks(ind + width / 2.0)
    ax.set_xticklabels(names, rotation=90, ha='center')
    ax.vlines(ind[::dataset_config['n_bands'] - 1],
              algo.feature_importances_.min(),
              algo.feature_importances_.max())
    plt.title('Feature Importance')
    plt.show()
