""" Command line interface for training classifiers on YATSM output """
from datetime import datetime as dt
from itertools import izip
import logging
import os

import click
import matplotlib.pyplot as plt
import numpy as np
from osgeo import gdal, ogr, osr
import csv

from sklearn.cross_validation import KFold, StratifiedKFold
from sklearn.externals import joblib
from yatsm.cli import options
from yatsm.config_parser import parse_config_file
from yatsm import classifiers
from yatsm.classifiers import diagnostics
from yatsm.errors import TrainingDataException
from yatsm import plots
from yatsm import reader
from yatsm import utils

logger = logging.getLogger('yatsm')

gdal.AllRegister()
gdal.UseExceptions()

if hasattr(plt, 'style') and 'ggplot' in plt.style.available:
    plt.style.use('ggplot')


@click.command(short_help='Train classifier on YATSM output')
@options.arg_config_file
@click.argument('classifier_config', metavar='<classifier_config>', nargs=1,
                type=click.Path(exists=True, readable=True,
                                dir_okay=False, resolve_path=True))
@click.argument('model', metavar='<model>', nargs=1,
                type=click.Path(writable=True, dir_okay=False,
                                resolve_path=True))
@click.option('--kfold', 'n_fold', nargs=1, type=click.INT, default=3,
              help='Number of folds in cross validation (default: 3)')
@click.option('--seed', nargs=1, type=click.INT,
              help='Random number generator seed')
@click.option('--yatsmlist', '-m', nargs=1, metavar='<yatsmlist>', 
              help='CSV with list of YATSM config files', default=False,
                type=click.Path(exists=True, readable=True,
                                dir_okay=False, resolve_path=True))
@click.option('--shapefile', '-s', nargs=1, metavar='<shapefile>', 
              help='ROI shapefile', default=False,
                type=click.Path(exists=True, readable=True,
                                dir_okay=False, resolve_path=True))
@click.option('--plot', is_flag=True, help='Show diagnostic plots')
@click.option('--diagnostics', is_flag=True, help='Run K-Fold diagnostics')
@click.option('--overwrite', is_flag=True, help='Overwrite output model file')
@click.pass_context
def train(ctx, config, classifier_config, model, n_fold, seed,
          plot, diagnostics, overwrite, yatsmlist, shapefile):
    """
    Train a classifier from `scikit-learn` on YATSM output and save result to
    file <model>. Dataset configuration is specified by <yatsm_config> and
    classifier and classifier parameters are specified by <classifier_config>.
    """
    # Setup
    if not model.endswith('.pkl'):
        model += '.pkl'
    if os.path.isfile(model) and not overwrite:
        logger.error('<model> exists and --overwrite was not specified')
        raise click.Abort()

    if seed:
        np.random.seed(seed)

    # Parse config & algorithm config
    cfg = parse_config_file(config)
    algo, algo_cfg = classifiers.cfg_to_algorithm(classifier_config)

    training_image = cfg['classification']['training_image']
    if not training_image or not os.path.isfile(training_image):
        logger.error('Training data image %s does not exist' % training_image)
        raise click.Abort()

    # Find information from results -- e.g., design info
    attrs = find_result_attributes(cfg)
    cfg['YATSM'].update(attrs)

    # Cache file for training data
    has_cache = False
    training_cache = cfg['classification']['cache_training']
    if training_cache:
        # If doesn't exist, retrieve it
        if not os.path.isfile(training_cache):
            logger.info('Could not retrieve cache file for Xy')
            logger.info('    file: %s' % training_cache)
        else:
            logger.info('Restoring X/y from cache file')
            has_cache = True

    training_image = cfg['classification']['training_image']
    # Check if we need to regenerate the cache file because training data is
    #   newer than the cache
    regenerate_cache = is_cache_old(training_cache, training_image)
    if regenerate_cache:
        logger.warning('Existing cache file older than training data ROI')
        logger.warning('Regenerating cache file')

    if not has_cache or regenerate_cache:
        logger.debug('Reading in X/y')
        if yatsmlist:
           X, y, row, col, labels = get_mult_train(shapefile, yatsmlist)
     	else:
           X, y, row, col, labels = get_training_inputs(cfg)
        logger.debug('Done reading in X/y')
    else:
        logger.debug('Reading in X/y from cache file %s' % training_cache)
        with np.load(training_cache) as f:
            X = f['X']
            y = f['y']
            row = f['row']
            col = f['col']
            labels = f['labels']
        logger.debug('Read in X/y from cache file %s' % training_cache)

    # If cache didn't exist but is specified, create it for first time
    if not has_cache and training_cache:
        logger.info('Saving X/y to cache file %s' % training_cache)
        try:
            np.savez(training_cache,
                     X=X, y=y, row=row, col=col, labels=labels)
        except:
            logger.error('Could not save X/y to cache file')
            raise

    # Do modeling
    logger.info('Training classifier')
    algo.fit(X, y, **algo_cfg.get('fit', {}))

    # Serialize algorithm to file
    logger.info('Pickling classifier with sklearn.externals.joblib')
    joblib.dump(algo, model, compress=3)

    # Diagnostics
    if diagnostics:
        algo_diagnostics(cfg, X, y, row, col, algo, n_fold, plot)


def is_cache_old(cache_file, training_file):
    """ Indicates if cache file is older than training data file
    Args:
        cache_file (str): filename of the cache file
        training_file (str): filename of the training data file_
    Returns:
        bool: True if the cache file is older than the training data file
            and needs to be updated; False otherwise
    """
    if cache_file and os.path.isfile(cache_file):
        return os.stat(cache_file).st_mtime < os.stat(training_file).st_mtime
    else:
        return False


def find_result_attributes(cfg):
    """ Return result attributes relevant for training a classifier
    At this time, the only relevant information is the design information.
    Args:
        cfg (dict): YATSM configuration dictionary
    Returns:
        dict: dictionary of result attributes. Includes 'design_info' key.
    """
    attrs = {
        'design_info': None
    }

    results = utils.find_results(cfg['dataset']['output'],
                                 cfg['dataset']['output_prefix'] + '*')
    for result in results:
        try:
            res = np.load(result)
            attrs['design_info'] = res['design_matrix'].item()
        except:
            pass
        else:
            return attrs
    raise AttributeError('Could not find following attributes in results: %s' %
                         attrs.keys())


def get_training_inputs(cfg, exit_on_missing=False):
    """ Returns X features and y labels specified in config file
    Args:
        cfg (dict): YATSM configuration dictionary
        exit_on_missing (bool, optional): exit if input feature cannot be found
    Returns:
        X (np.ndarray): matrix of feature inputs for each training data sample
        y (np.ndarray): array of labeled training data samples
        row (np.ndarray): row pixel locations of `y`
        col (np.ndarray): column pixel locations of `y`
        labels (np.ndarraY): label of `y` if found, else None
    """
    # Find and parse training data
    roi = reader.read_image(cfg['classification']['training_image'])
    logger.debug('Read in training data')
    if len(roi) == 2:
        logger.info('Found labels for ROIs -- including in output')
        labels = roi[1]
    else:
        roi = roi[0]
        labels = None

    # Determine start and end dates of training sample relevance
    try:
        training_start = dt.strptime(
            cfg['classification']['training_start'],
            cfg['classification']['training_date_format']).toordinal()
        training_end = dt.strptime(
            cfg['classification']['training_end'],
            cfg['classification']['training_date_format']).toordinal()
    except:
        logger.error('Failed to parse training data start or end dates')
        raise

    # Loop through samples in ROI extracting features
    mask_values = cfg['classification']['roi_mask_values']
    mask = ~np.in1d(roi, mask_values).reshape(roi.shape)
    row, col = np.where(mask)
    y = roi[row, col]

    X = []
    out_y = []
    out_row = []
    out_col = []

    _row_previous = None
    for _row, _col, _y in izip(row, col, y):
        # Load result
        if _row != _row_previous:
            output_name = utils.get_output_name(cfg['dataset'], _row)
            try:
                rec = np.load(output_name)['record']
                _row_previous = _row
            except:
                logger.error('Could not open saved result file %s' %
                             output_name)
                if exit_on_missing:
                    raise
                else:
                    continue
	#import pdb; pdb.set_trace()
        # Find intersecting time segment
	try:
            i = np.where((rec['start'] < training_start) &
                         (rec['end'] > training_end) &
                         (rec['px'] == _col))[0]
        except:
            logger.debug('Could not find model for label %i at x/y %i/%i' %
                         (_y, _col, _row))
            continue
        if i.size == 0:
            logger.debug('Could not find model for label %i at x/y %i/%i' %
                         (_y, _col, _row))
            continue
        elif i.size > 1:
            raise TrainingDataException(
                'Found more than one valid model for label %i at x/y %i/%i' %
                (_y, _col, _row))

        # Extract coefficients with intercept term rescaled
        coef = rec[i]['coef'][0, :]
        coef[0, :] = (coef[0, :] +
                      coef[1, :] * (rec[i]['start'] + rec[i]['end']) / 2.0)

        X.append(np.concatenate((coef.reshape(coef.size), rec[i]['rmse'][0])))
        out_y.append(_y)
        out_row.append(_row)
        out_col.append(_col)

    out_row = np.array(out_row)
    out_col = np.array(out_col)

    if labels is not None:
        labels = labels[out_row, out_col]

    return np.array(X), np.array(out_y), out_row, out_col, labels


def algo_diagnostics(cfg, X, y,
                     row, col, algo, n_fold, make_plots=True):
    """ Display algorithm diagnostics for a given X and y
    Args:
        cfg (dict): YATSM configuration dictionary
        X (np.ndarray): X feature input used in classification
        y (np.ndarray): y labeled examples
        row (np.ndarray): row pixel locations of `y`
        col (np.ndarray): column pixel locations of `y`
        algo (sklearn classifier): classifier used from scikit-learn
        n_fold (int): number of folds for crossvalidation
        make_plots (bool, optional): show diagnostic plots (default: True)
    """
    # Print algorithm diagnostics without crossvalidation
    logger.info('<----- DIAGNOSTICS ----->')
    if hasattr(algo, 'oob_score_'):
        logger.info('Out of Bag score: %f' % algo.oob_score_)

    kfold_summary = np.zeros((0, 2))
    test_names = ['KFold', 'Stratified KFold', 'Spatial KFold (shuffle)']

    def report(kf):
        logger.info('<----------------------->')
        logger.info('%s crossvalidation scores:' % kf.__class__.__name__)
        try:
            scores = diagnostics.kfold_scores(X, y, algo, kf)
        except Exception as e:
            logger.warning('Could not perform %s cross-validation: %s' %
                           (kf.__class__.__name__, e.message))
        else:
            return scores

    kf = KFold(y.size, n_folds=n_fold)
    kfold_summary = np.vstack((kfold_summary, report(kf)))

    kf = StratifiedKFold(y, n_folds=n_fold)
    kfold_summary = np.vstack((kfold_summary, report(kf)))

    kf = diagnostics.SpatialKFold(y, row, col, n_folds=n_fold, shuffle=True)
    kfold_summary = np.vstack((kfold_summary, report(kf)))

    if make_plots:
        plots.plot_crossvalidation_scores(kfold_summary, test_names)

    logger.info('<----------------------->')
    if hasattr(algo, 'feature_importances_'):
        logger.info('Feature importance:')
        logger.info(algo.feature_importances_)
        if make_plots:
            plots.plot_feature_importance(algo, cfg)



#Start functions for training using multiple path rows
def get_mult_train(shape, YATSMfile):

    """ Returns X features and y labels specified in config file
    Args:
	shape (OGR vector): ROI shapefile. One column is ROI, one is PathRow
	YATSMfile (np array): CSV of YATSM config files
        cfg (dict): YATSM configuration dictionary
	prs (array): Array of Path Rows used in training

    Returns:
        X (np.ndarray): matrix of feature inputs for each training data sample
        y (np.ndarray): array of labeled training data samples
        row (np.ndarray): row pixel locations of `y`
        col (np.ndarray): column pixel locations of `y`
        labels (np.ndarraY): label of `y` if found, else None
	"""

    rasterlist=[]
    X=[]
    Y=[]
    num=[]
    driver = ogr.GetDriverByName("ESRI Shapefile")
    dataSource = driver.Open(shape, 0)
    layer = dataSource.GetLayer()

    #Turn CSV with list of YATSM config files into list
    with open(YATSMfile, 'rb') as f:
          reader = csv.reader(f)
	  #import pdb; pdb.set_trace()
	  yatsmlist = list(reader)

    #Rasterlist is list of example rasters
    rastlist, outputlist, prlist=get_rast_list(yatsmlist)


    #prlist=get_prs(layer)
    x=[]
    y=[]
    out_row=[]
    out_col=[]
    labels=[]
    #Loop over path rows, creating a memory vector for each
    for num,pr in enumerate(prlist):
	input_value_raster=rastlist[num]
        rast = gdal.Open(input_value_raster)
        #Get srs stuff from raster list
        raster_srs = osr.SpatialReference()
        raster_srs.ImportFromWkt(rast.GetProjectionRef())
        #Create memory vectors layer for features
        driver = ogr.GetDriverByName('MEMORY')
        out_ds = driver.CreateDataSource('tmp')
        out_layer = out_ds.CreateLayer('out', geom_type=ogr.wkbPolygon, srs=raster_srs)
        vector_srs = layer.GetSpatialRef()
        coord_trans = osr.CoordinateTransformation(vector_srs, raster_srs)
       # featureDefn = out_layer.GetLayerDefn()
       # feature = ogr.Feature(featureDefn)
	#Loop over layer and add appropriate features to memory vector
 	for feat in layer:
	    pathrow = feat.GetField('PR')
            if pathrow == pr:
                featureDefn = out_layer.GetLayerDefn()
		feature = ogr.Feature(featureDefn)
                geom = feat.GetGeometryRef()
                geom.Transform(coord_trans)
                feature.SetGeometry(geom)
                out_layer.CreateFeature(feat)
            else:
                continue
	#Now rasterize the memory vector to the extent of the example image
        memLayer = out_ds.GetLayer()
	trainingraster= rasterize_mem(rast, memLayer, out_ds)
        #Now that we have the memory vector for that file we can do the training
        _x, _y, _out_row, _out_col, _labels = get_mult_training_inputs(yatsmlist[num], trainingraster, memLayer)
        #import pdb; pdb.set_trace()
        x.append(_x)
        y.append(_y)
        out_row.append(_out_row)
        out_col.append(_out_col)
        labels.append(_labels)
	memLayer = None
	trainingraster = None
    return np.array(x), np.array(y), np.array(out_row), np.array(out_col), np.array(labels)

def rasterize_mem(raster, memlayer, memvector):
    """ Returns X features and y labels specified in config file
    Args:
	raster (GDAL raster): Input example raster
	memlayer (OGR Memory Array): memory layer with features for training

    Returns:
        trainraster (GDAL Raster): Raster with training classes burned in
	"""

    gt = raster.GetGeoTransform()
    ul_x, ul_y = gt[0], gt[3]
    ps_x, ps_y = gt[1], gt[5]
    xmin, xmax, ymin, ymax = memlayer.GetExtent()
    xoff = int((xmin - ul_x) / ps_x)
    yoff = int((ul_y - ymax) / ps_x)
    xcount = int((xmax - xmin) / ps_x) + 1
    ycount = int((ymax - ymin) / ps_x) + 1
    target_ds = gdal.GetDriverByName('MEM').Create('', xcount, ycount, 1, gdal.GDT_UInt32)
    raster_srs = osr.SpatialReference()
    raster_srs.ImportFromWkt(raster.GetProjectionRef())
    target_ds.SetProjection(raster_srs.ExportToWkt())
    target_ds.SetGeoTransform((xmin, ps_x, 0,
                                   ymax, 0, ps_y))

    for feat in memlayer:
	print feat.GetField('ID')
     # Rasterize zone polygon to raster
    print "about to be rasterized"
    #fid_layer = memvector.ExecuteSQL(
    #    'select ID, * from "{l}"'.format(l=memlayer.GetName()))
    #import pdb; pdb.set_trace()
    mem2=memvector.GetLayer()
    #import pdb; pdb.set_trace()
    gdal.RasterizeLayer(target_ds, [1], mem2, burn_values=[0], options=["ATTRIBUTE=PRksjf", "ALL_TOUCHED=TRUE"])
    print "rasterized"

    return target_ds

def get_prs(layer):

    """ Get the Path Rows we will be using for training
    Args:
	shape (OGR vector): ROI shapefile. One column is ROI, one is PathRow

    Returns:
        prs (np.ndarray): array with list of prs in ROIs """

    prs_all = []
    for feature in layer:
	try:
            Date = feature.GetField('PRs')
            print Date
            prs_all.append(Date)
	except:
	    print "No attribute called PRs in %s" % feature
    prs=np.unique(prs_all)
    return prs

def get_mult_training_inputs(curyat,trainingraster, trainingvector, exit_on_missing=False):
    """ Returns X features and y labels specified in config file
    Args:
	TODO:
        cfg (dict): YATSM configuration dictionary
    Returns:
        X (np.ndarray): matrix of feature inputs for each training data sample
	TODO
    """
    # Find and parse training data
#    import pdb; pdb.set_trace()
    print curyat
    cfg = parse_config_file(curyat[0])
    roi = reader.read_image(trainingraster)
    logger.debug('Read in training data')
    if len(roi) == 2:
        logger.info('Found labels for ROIs -- including in output')
        labels = roi[1]
    else:
        roi = roi[0]
        labels = None

    # Determine start and end dates of training sample relevance
    try:
        training_start = dt.strptime(
            cfg['classification']['training_start'],
            cfg['classification']['training_date_format']).toordinal()
        training_end = dt.strptime(
            cfg['classification']['training_end'],
            cfg['classification']['training_date_format']).toordinal()
    except:
        logger.error('Failed to parse training data start or end dates')
        raise

    # Loop through samples in ROI extracting features
    mask_values = cfg['classification']['roi_mask_values']
    mask = ~np.in1d(roi, mask_values).reshape(roi.shape)
    row, col = np.where(mask)
    y = roi[row, col]
    X = []
    out_y = []
    out_row = []
    out_col = []

    _row_previous = None
    for _row, _col, _y in izip(row, col, y):
        # Load result
        if _row != _row_previous:
            output_name = utils.get_output_name(cfg['dataset'], _row)
            try:
                rec = np.load(output_name)['record']
                _row_previous = _row
            except:
                logger.error('Could not open saved result file %s' %
                             output_name)
                if exit_on_missing:
                    raise
                else:
                    continue

        # Find intersecting time segment
        i = np.where((rec['start'] < training_start) &
                     (rec['end'] > training_end) &
                     (rec['px'] == _col))[0]

        if i.size == 0:
            logger.debug('Could not find model for label %i at x/y %i/%i' %
                         (_y, _col, _row))
            continue
        elif i.size > 1:
            raise TrainingDataException(
                'Found more than one valid model for label %i at x/y %i/%i' %
                (_y, _col, _row))

        # Extract coefficients with intercept term rescaled
        coef = rec[i]['coef'][0, :]
        coef[0, :] = (coef[0, :] +
                      coef[1, :] * (rec[i]['start'] + rec[i]['end']) / 2.0)

        X.append(np.concatenate((coef.reshape(coef.size), rec[i]['rmse'][0])))
        out_y.append(_y)
        out_row.append(_row)
        out_col.append(_col)

    out_row = np.array(out_row)
    out_col = np.array(out_col)

    if labels is not None:
        labels = labels[out_row, out_col]

    return np.array(X), np.array(out_y), out_row, out_col, labels


def get_rast_list(yatsmlist):
    """
    Args:

    Returns:
    rasterlist (..): List of training images
    outputlist (..): List of paths to YATSM output folders
    """


    rastlist=[]
    outputlist=[]
    PRlist=[]
    for yat in yatsmlist:
	cfg = parse_config_file(yat[0])
        rastlist.append(cfg['classification']['training_image'])
        outputlist.append(cfg['dataset']['output'])
        PRlist.append(cfg['classification']['pathrow'])

    return rastlist, outputlist, PRlist