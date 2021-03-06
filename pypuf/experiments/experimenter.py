"""
This module provides a class which acts as process pool. The is build in order to distribute several experiments over
the system cores. The results of the experiments are written into on a single log file which is coordinated by a logging
process. In order to run experiments a path to a logfile and list of experiments is needed which inherit the
pypuf.experiments.experiment.base class.

Example usage:

experiments = []
n = 128
for i in range(n):
    log_name = 'test_multiprocessing_logs{0}'.format(i)
    experiment = Experiment(...)
    experiments.append(experiment)

experimenter = Experimenter('experimenter_log_path', experiments)
experimenter.run()
"""
import multiprocessing
import logging
import sys
import traceback


class Experimenter(object):
    """
    Coordinated, parallel execution of Experiments with logging.
    """

    def __init__(self, log_name, experiments, cpu_limit=2**16):
        """
        :param experiments: A list of pypuf.experiments.experiment.base.Experiment
        :param log_name: A unique file path where to output should be logged.
        :param cpu_limit: Maximum number of parallel processes that run experiments.
        """

        # Store experiments list
        self.experiments = experiments

        # Store logger name
        self.logger_name = log_name

        # Setup parallel execution limit
        self.cpu_limit = min(cpu_limit, multiprocessing.cpu_count())
        self.semaphore = multiprocessing.BoundedSemaphore(self.cpu_limit)

    def run(self):
        """
        Runs all experiments.
        """

        # Setup multiprocessing logging
        queue = multiprocessing.Queue(-1)
        listener = multiprocessing.Process(target=log_listener,
                                           args=(queue, setup_logger, self.logger_name,))
        listener.start()

        # list of active jobs
        active_jobs = []

        for exp in self.experiments:

            # define experiment process
            def run_experiment(experiment, queue, semaphore, logger_name):
                """
                This method is responsible to start the experiment and release the semaphore which coordinates the
                number of parallel running processes.
                :param experiment: pypuf.experiments.experiment.base.Experiment
                                   A implementation of the base experiment class which should be executed
                :param queue: multiprocessing.queue
                              This is used to coordinate the processes in order to obtain results.
                :param semaphore: multiprocessing.BoundedSemaphore(self.cpu_limit)
                                  A semaphore to limit the number of concurrent running experiments
                :param logger_name: String
                                    Path to or name to the log file of the experiment
                """
                try:
                    experiment.execute(queue, logger_name)  # run the actual experiment
                    semaphore.release()  # release CPU
                except Exception as experiment:  # pylint: disable=W
                    semaphore.release()  # release CPU
                    raise experiment

            job = multiprocessing.Process(
                target=run_experiment,
                args=(exp, queue, self.semaphore, self.logger_name)
            )

            # wait for a free CPU
            self.semaphore.acquire()

            def list_active_jobs():
                """
                update list of active jobs
                return: [multiprocessing.Process] list of active jobs
                """
                still_active_jobs = []
                for j in active_jobs:
                    j.join(0)
                    if j.exitcode is None:
                        still_active_jobs.append(j)
                return still_active_jobs

            # start experiment
            job.start()
            active_jobs = list_active_jobs()
            active_jobs.append(job)

        # wait for all processes to be finished
        for job in active_jobs:
            job.join()

        # Quit logging process
        queue.put_nowait(None)
        listener.join()


def setup_logger(logger_name):
    """
    This method is used to open the file handler for a logger_name. The resulting log file will have the format
    'logger_namer.log'.
    :param logger_name: string
                        Path to or name to the log file
    """
    root = logging.getLogger(logger_name)

    # Setup logging to both file and console
    file_handler = logging.FileHandler(filename='%s.log' % logger_name, mode='w')
    file_handler.setLevel(logging.INFO)

    root.addHandler(file_handler)


def log_listener(queue, configurer, logger_name):
    """
    This is the root function of logging process which is responsible to log the experiment results.
    :param queue: multiprocessing.queue
                  This is used to coordinate the processes in order to obtain results.
    :param configurer: A function which setup the logger which logs the messages read from the queue.
    :param logger_name: String
                        Path to or name to the log file
    """
    configurer(logger_name)
    while True:
        try:
            record = queue.get()
            if record is None:  # We send this as a sentinel to tell the listener to quit.
                break
            logger = logging.getLogger(record.name)
            logger.handle(record)  # No level or filter logic applied - just do it!
        except Exception:  # pylint: disable=W
            print('Whoops! Problem:', file=sys.stderr)
            traceback.print_exc(file=sys.stderr)
