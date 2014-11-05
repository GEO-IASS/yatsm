Running the Model
=================

Batch Interface
---------------

The default method for running image stacks is to run each line, or row,
separately from other lines. In a multiprocessing situation, the total
number of lines can be broken up among the ``n`` available CPUs. Before
using the batch interface, make sure you already have a parameter file
generated as described by `Section 2 - Batch Process
Configuration <2_model_config.md>`__.

The batch interface which runs each line separately is
``line_yatsm.py``. It's usage is:

.. code:: sh

    $ ./yatsm/line_yatsm.py -h
     Yet Another Timeseries Model (YATSM) - run script for lines of images

    Usage: line_yatsm.py [options] <config_file> <job_number> <total_jobs>

    Options:
        --check                     Check that images exist
        --resume                    Do not overwrite pre-existing results
        -v --verbose                Show verbose debugging messages
        --verbose-yatsm             Show verbose debugging messages in YATSM
        -q --quiet                  Show only error messages
        -h --help                   Show help

-  ``<config_file>``: filename of the configuration INI file.
-  ``<job_number>``: the ``i``\ th job of ``n`` total jobs
-  ``<total_jobs>``: the total number of jobs used to process the image
   stack

Let's say our image stack contains 1,000 rows. If we use 50 total CPUs
to process the image stack, then each CPU will be responsible for only
20 lines. To evenly distribute the number of pixels that contain
timeseries (e.g., to ignore any NODATA buffers around the images), the
lines are divided up in sequence. Thus, job 5 of 50 total jobs would
work on the lines:

.. code:: sh

    $ job=5
    $ n=50
    $ seq -s , $job $n 1000
    5,55,105,155,205,255,305,355,405,455,505,555,605,655,705,755,805,855,905,955

Sun Grid Engine
---------------

In the example of the compute cluster at Boston University which
utilizes the Sun Grid Engine scheduler, one could run an image stack as
follows:

.. code:: sh

    $ njob=200
    $ for job in $(seq 1 $njob); do
        qsub -j y -V -l h_rt=24:00:00 -N yatsm_$job -b y \
            $(which python) -u line_yatsm.py --resume -v config.ini $job $njob
      done

