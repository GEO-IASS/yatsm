Yet Another Timeseries Model (YATSM)
------------------------------------
## About
YATSM model based off of tests for structural changes from the econometrics literature including the MOSUM or CUMSUM (Chu et al, Zeileis, and others) as implemented in a remote sensing context by BFAST (Verbesselt, et al. 2012) and CCDC (Zhu and Woodcock, 2014). This effort is not intended as a direct port of either algorithm. The "YATSM" name intends to refer to these two algorithms without claiming 1 to 1 functionality of either.

## Requirements
#### Main dependencies:

    Python (2.7.x tested)
    GDAL (1.10.0 tested)

#### Python dependencies:
Listed below are the Python library requirements for running YATSM. The version numbers listed are the versions I've used for development, but I suspect the versions are flexible.

    numpy=1.8.1
    pandas=0.13.1
    statsmodels=0.5.0
    glmnet=1.1-5 (see: https://github.com/dwf/glmnet-python)
    scikit-learn=0.14.1
    ggplot=0.5.8
    docopt=0.6.1
