""" Command line interface for running YATSM algorithms on individual pixels
"""
import datetime as dt
import logging
import re
from datetime import date
try:
    from IPython import embed as IPython_embed
    has_embed = True
except:
    has_embed = False

import click
import matplotlib as mpl
import matplotlib.pyplot as plt
import numpy as np
import palettable
import patsy
import yaml

from yatsm.algorithms import postprocess  # TODO: implement postprocessors
from yatsm.cli import options
from yatsm.config_parser import convert_config, parse_config_file
from yatsm import _cyprep as cyprep
from yatsm.utils import csvfile_to_dataframe, get_image_IDs
from yatsm.reader import read_pixel_timeseries
from yatsm.regression.transforms import harm  # noqa
from rpy2 import robjects as ro
from rpy2.robjects.packages import importr
import rpy2.robjects.numpy2ri
rpy2.robjects.numpy2ri.activate()
Rstats = importr('stats')

avail_plots = ['TS', 'DOY', 'VAL']
plot_styles = []
if hasattr(mpl, 'style'):
    plot_styles = mpl.style.available
if hasattr(plt, 'xkcd'):
    plot_styles.append('xkcd')

logger = logging.getLogger('yatsm')


@click.command(short_help='Run YATSM algorithm on individual pixels')
@options.arg_config_file
@click.argument('px', metavar='<px>', nargs=1, type=click.INT)
@click.argument('py', metavar='<py>', nargs=1, type=click.INT)
@click.option('--band', metavar='<n>', nargs=1, type=click.INT, default=1,
              show_default=True, help='Band to plot')
@click.option('--plot', default=('TS',), multiple=True, show_default=True,
              type=click.Choice(avail_plots), help='Plot type')
@click.option('--ylim', metavar='<min> <max>', nargs=2, type=float,
              show_default=True, help='Y-axis limits')
@click.option('--style', metavar='<style>', default='ggplot',
              show_default=True, type=click.Choice(plot_styles),
              help='Plot style')
@click.option('--cmap', metavar='<cmap>', default='perceptual_rainbow_16',
              show_default=True, help='DOY plot colormap')
@click.option('--embed', is_flag=True,
              help='Drop to embedded IPython shell at various points')
@click.option('--seed', help='Set NumPy RNG seed value')
@click.option('--algo_kw', multiple=True, callback=options.callback_dict,
              help='Algorithm parameter overrides')
@click.pass_context
def pixel(ctx, config, px, py, band, plot, ylim, style, cmap,
          embed, seed, algo_kw):
    # Set seed
    np.random.seed(seed)
    # Convert band to index
    band -= 1

    # Get colormap
    if hasattr(palettable.colorbrewer, cmap):
        mpl_cmap = getattr(palettable.colorbrewer, cmap).mpl_colormap
    elif hasattr(palettable.cubehelix, cmap):
        mpl_cmap = getattr(palettable.cubehelix, cmap).mpl_colormap
    elif hasattr(palettable.wesanderson, cmap):
        mpl_cmap = getattr(palettable.wesanderson, cmap).mpl_colormap
    else:
        raise click.Abort('Cannot find specified colormap in `palettable`')

    # Parse config
    cfg = parse_config_file(config)

    # Apply algorithm overrides
    revalidate = False
    for kw in algo_kw:
        for cfg_key in cfg:
            if kw in cfg[cfg_key]:
                # Parse as YAML for type conversions used in config parser
                value = yaml.load(algo_kw[kw])

                print('Overriding cfg[%s][%s]=%s with %s' %
                      (cfg_key, kw, cfg[cfg_key][kw], value))
                cfg[cfg_key][kw] = value
                revalidate = True

    if revalidate:
        cfg = convert_config(cfg)

    # Locate and fetch attributes from data
    df = csvfile_to_dataframe(cfg['dataset']['input_file'],
                              date_format=cfg['dataset']['date_format'])
    df['image_ID'] = get_image_IDs(df['filename'])

    # Setup X/Y
    kws = {'x': df['date']}
    kws.update(df.to_dict())
    X = patsy.dmatrix(cfg['YATSM']['design_matrix'], kws)
    design_info = X.design_info

    Y = read_pixel_timeseries(df['filename'], px, py)

    fit_indices = np.arange(cfg['dataset']['n_bands'])
    if cfg['dataset']['mask_band'] is not None:
        fit_indices = fit_indices[:-1]

    # Mask out of range data
    idx_mask = cfg['dataset']['mask_band'] - 1
    valid = cyprep.get_valid_mask(Y,
                                  cfg['dataset']['min_values'],
                                  cfg['dataset']['max_values']).astype(np.bool)
    valid *= np.in1d(Y[idx_mask, :], cfg['dataset']['mask_values'],
                     invert=True).astype(np.bool)

    # Apply mask
    Y = np.delete(Y, idx_mask, axis=0)[:, valid]
    X = X[valid, :]
    dates = np.array([dt.datetime.fromordinal(d) for d in df['date'][valid]])
    #np.save('/projectnb/landsat/users/bullocke/Thailand/Proposal/Landsat/YATSM_Files/examples/dates_5287_5512.npy', dates)
    #np.save('/projectnb/landsat/users/bullocke/Thailand/Proposal/Landsat/YATSM_Files/examples/x_5287_5512.npy', X)
    #np.save('/projectnb/landsat/users/bullocke/Thailand/Proposal/Landsat/YATSM_Files/examples/y_5287_5512.npy', Y)

    # Plot before fitting
   # with plt.xkcd() if style == 'xkcd' else mpl.style.context(style):
   #     for _plot in plot:
   #         if _plot == 'TS':
   #             plot_TS(dates, Y[band, :])
   #         elif _plot == 'DOY':
   #             plot_DOY(dates, Y[band, :], mpl_cmap)
   #         elif _plot == 'VAL':
   #             plot_VAL(dates, Y[band, :], mpl_cmap)

  #          if ylim:
  #              plt.ylim(ylim)
  #          plt.title('Timeseries: px={px} py={py}'.format(px=px, py=py))
  #          plt.ylabel('Band {b}'.format(b=band + 1))

 #           if embed and has_embed:
 #               IPython_embed()

#            plt.tight_layout()
#            plt.show()

    # Eliminate config parameters not algorithm and fit model
    yatsm = cfg['YATSM']['algorithm_cls'](lm=cfg['YATSM']['prediction_object'],
                                          **cfg[cfg['YATSM']['algorithm']])
    yatsm.px = px
    yatsm.py = py
    yatsm.fit(X, Y, np.asarray(df['date'][valid]))

    # Plot after predictions
    with plt.xkcd() if style == 'xkcd' else mpl.style.context(style):
        for _plot in plot:
            if _plot == 'TS':
	        fig, ax1 = plt.subplots()
                ax1.scatter(dates, Y[band,:], c='k', marker='o', edgecolors='black', s=35)
		ax1.set_axis_bgcolor('white')
                plt.xlabel('Date') 
            elif _plot == 'DOY':
                plot_DOY(dates, Y[band, :], mpl_cmap)
            elif _plot == 'VAL':
                plot_VAL(dates, Y[band, :], mpl_cmap)

            if ylim:
                plt.ylim(ylim)
	        #plt.xlim((2005,2010))
#            plt.title('Timeseries: px={px} py={py}'.format(px=px, py=py))
	    hfont = {'fontname': 'Liberation Sans'}
            ax1.set_ylabel('Landsat TM/ETM Band {b}'.format(b=band + 1), fontsize=20, **hfont)

            plot_results(ax1, band, cfg['YATSM'], yatsm, plot_type=_plot)

            if embed and has_embed:
                IPython_embed()


            radx=[date(2007, 1, 29), date(2007,8, 8), date(2007,11,11), date(2007,12,16), date(2008, 3, 18), date(2009, 2, 3), date(2009, 12, 22)]
	    radyDN=[.259, .213, .229, .319, .201, .175, .133]
            inc = [.2718, .2841, .2753, .281, .2811, .2759, .2667]
	    sigma=(np.array(radyDN))*(np.array(inc))
	    #rady=[.259, .213, .229, .319, .201, .175, .133]
            rady = 10*np.log10(sigma)
#	    rady = [(10 * (np.log10(x.astype(float)**2)) + (-83)) for x in np.array(radyDN)]
            #rady = [(10 * np.log10((x/1000).astype(float)*(x/1000).astype(float)) + (-83)) for x in radyDN]
	    x2 = np.array([dt.datetime.toordinal(d) for d in radx])
#	    import pdb; pdb.set_trace()
	    s = Rstats.smooth_spline(x2, np.array(rady), spar=1)
	    xs = np.linspace(x2.min(), x2.max(), np.shape(x2)[0])
	    ys_ob = Rstats.predict(s,xs)
            ys = np.array(ys_ob)

	    ax2 = ax1.twinx()
	    ax2.set_axis_bgcolor('white')
            ax2.scatter(radx, rady, c='r', marker='^', edgecolors='black', s=45, )
            ax2.set_ylabel('Backscatter (db)')
            ax1.set_ylim(750, 2250)
            ax2.set_ylim(-20, -5)
	    ax2.plot(ys[0,:], ys[1,:], linestyle='dashed', c='r', label='PALSAR Spline Fit')
	    ax2.yaxis.label.set_size(15)
	    ax1.xaxis.label.set_size(15)
	    ax1.yaxis.label.set_size(15)
	    plt.xlim((date(2005,1,1),date(2010,2,1)))
	    lines, labels = ax1.get_legend_handles_labels()
	    lines2, labels2 = ax2.get_legend_handles_labels()
	    #legend = ax2.legend(lines + lines2, labels + labels2, loc=9, prop={'size':14})
	    #legend.get_frame().set_facecolor('white')
	    #legend.get_frame().set_edgecolor('black')
#	    ax1.grid(b=True)
#	    ax2.grid(b=True)
	    fig.set_size_inches(11, 3, forward=True)
            plt.tight_layout()
            ax1.tick_params(labelsize=12)
            ax2.tick_params(labelsize=12)
	    plt.savefig('/projectnb/landsat/users/bullocke/Thailand/Proposal/Landsat/YATSM_Files/examples/combined_ts_adjusted_legend.png')
            plt.show()


def plot_TS(dates, y):
    # Plot data
    plt.scatter(dates, y, c='k', marker='o', edgecolors='black', s=35)
    plt.xlabel('Date')
    hfont = {'fontname':'Liberation Sans'}
    fig = plt.figure()
    fig.set_size_inches(11, 3)
    plt.ylim([2000,5000])
    plt.scatter(dates, y, c='k', marker='o', edgecolors='none', s=35)
    plt.tick_params(labelsize=20)
    plt.xlabel('Date', fontsize=20, **hfont)

def plot_DOY(dates, y, mpl_cmap):
    doy = np.array([d.timetuple().tm_yday for d in dates])
    year = np.array([d.year for d in dates])

    sp = plt.scatter(doy, y, c=year, cmap=mpl_cmap,
                     marker='o', edgecolors='black', s=35)
    plt.colorbar(sp)

    months = mpl.dates.MonthLocator()  # every month
    months_fmrt = mpl.dates.DateFormatter('%b')

    plt.tick_params(axis='x', which='minor', direction='in', pad=-10)
    plt.axes().xaxis.set_minor_locator(months)
    plt.axes().xaxis.set_minor_formatter(months_fmrt)

    plt.xlim(1, 366)
    plt.xlabel('Day of Year')


def plot_VAL(dates, y, mpl_cmap, reps=2):
    doy = np.array([d.timetuple().tm_yday for d in dates])
    year = np.array([d.year for d in dates])

    # Replicate `reps` times
    _doy = doy.copy()
    for r in range(1, reps + 1):
        _doy = np.concatenate((_doy, doy + r * 366))
    _year = np.tile(year, reps + 1)
    _y = np.tile(y, reps + 1)

    sp = plt.scatter(_doy, _y, c=_year, cmap=mpl_cmap,
                     marker='o', edgecolors='black', s=35)
    plt.colorbar(sp)
    plt.xlabel('Day of Year')


def plot_results(ax1, band, yatsm_config, yatsm_model, plot_type='TS'):
    step = -1 if yatsm_config['reverse'] else 1
    design = re.sub(r'[\+\-][\ ]+C\(.*\)', '', yatsm_config['design_matrix'])

    for i, r in enumerate(yatsm_model.record):
        #label = 'Model {i}'.format(i=i)
        label = 'CCDC Timeseries'
        if plot_type == 'TS':
            mx = np.arange(r['start'], r['end'], step)
            mX = patsy.dmatrix(design, {'x': mx}).T

            my = np.dot(r['coef'][:, band], mX)
            mx_date = np.array([dt.datetime.fromordinal(int(_x)) for _x in mx])

        elif plot_type == 'DOY':
            yr_end = dt.datetime.fromordinal(r['end']).year
            yr_start = dt.datetime.fromordinal(r['start']).year
            yr_mid = int(yr_end - (yr_end - yr_start) / 2)

            mx = np.arange(dt.date(yr_mid, 1, 1).toordinal(),
                           dt.date(yr_mid + 1, 1, 1).toordinal(), 1)
            mX = patsy.dmatrix(design, {'x': mx}).T

            my = np.dot(r['coef'][:, band], mX)
            mx_date = np.array([dt.datetime.fromordinal(d).timetuple().tm_yday
                                for d in mx])

            label = 'Model {i} - {yr}'.format(i=i, yr=yr_mid)

        ax1.plot(mx_date, my, lw=4, label=label, c='black')
        #plt.legend()


def plot_lasso_debug(model):
    """ See example:
    http://scikit-learn.org/stable/auto_examples/linear_model/plot_lasso_model_selection.html
    """
    m_log_alphas = -np.log10(model.alphas_)
    plt.plot(m_log_alphas, model.mse_path_, ':')
    plt.plot(m_log_alphas, model.mse_path_.mean(axis=-1), 'k',
             label='Average across the folds', linewidth=2)
    plt.axvline(-np.log10(model.alpha_), linestyle='--', color='k',
                label='alpha: CV estimate')
    plt.xlabel('-log(alpha)')
    plt.ylabel('Mean square error')
    plt.title('Mean square error on each fold: coordinate descent')


# UTILITY FUNCTIONS
def type_convert(value, example):
    """ Convert value (str) to dtype of `example`

    Args:
      value (str): string value to convert type
      example (int, float, bool, list, tuple, np.ndarray, etc.): `value`
        converted to type of `example` variable

    """
    dtype = type(example)
    if dtype is int:
        return int(value)
    elif dtype is float:
        return float(value)
    elif dtype in (list, tuple, np.ndarray):
        _dtype = type(example[0])
        return np.array([_dtype(v) for v in value.replace(',', ' ').split(' ')
                         if v])
    elif dtype is bool:
        if value.lower()[0] in ('t', 'y'):
            return True
        else:
            return False
