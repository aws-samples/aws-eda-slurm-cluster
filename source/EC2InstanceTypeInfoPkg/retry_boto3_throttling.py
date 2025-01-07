#!/usr/bin/env python3

from botocore.exceptions import ClientError
from functools import wraps
import logging
from logging import error, info, warning, handlers
import random
import time
import traceback

logger = logging.getLogger(__file__)

logger_formatter = logging.Formatter('%(levelname)s:%(asctime)s: %(message)s')
logger_streamHandler = logging.StreamHandler()
logger_streamHandler.setFormatter(logger_formatter)
logger.addHandler(logger_streamHandler)
logger.setLevel(logging.INFO)
#logger.setLevel(logging.DEBUG)

def retry_boto3_throttling(min_delay = 1, max_delay = 10 * 60, max_cumulative_delay = 12 * 3600, base = 1, logger = logger):
    """
    Retry calling the decorated function using a linear or exponential backoff.

    This is to handle EC2 API and resource throttling which uses a token bucket
    with a fixed refill rate. Once the bucket is emptied then throttling occurs
    until tokens are added. Tokens are added every second so the minimum retry
    interval is 1 second up to the specified maximum delay.

    I think I like this one better since it randomly spreads the backoff while
    still allowing some short backoffs.

    https://aws.amazon.com/blogs/architecture/exponential-backoff-and-jitter/

    http://www.saltycrane.com/blog/2009/11/trying-out-retry-decorator-python/
    original from: http://wiki.python.org/moin/PythonDecoratorLibrary#Retry

    Decorators described here:
    https://docs.python.org/2/whatsnew/2.4.html?highlight=decorator#pep-318-decorators-for-functions-and-methods

    :param min_delay: Minimum delay before retry
    :type min_delay: int

    :param max_delay: Maximum delay before retry
    :type max_delay: int

    :param max_cumulative_delay: Maximum total time to wait in seconds
    :type max_cumulative_delay: int

    :param base: Base for exponential backoff
    :type base: int

    :param logger: logger to use.
    :type logger: logging.Logger instance
    """
    def deco_retry(f):

        @wraps(f)
        def f_retry(*args, **kwargs):
            attempt = 0
            cumulative_delay = 0.0
            while (cumulative_delay < max_cumulative_delay):
                try:
                    attempt += 1
                    return f(*args, **kwargs)
                except ClientError as e:
                    logging.debug("Caught exception")
                    if e.response['Error']['Code'] in ['RequestLimitExceeded', 'InternalError', 'ThrottlingException']:
                        pass
                    else:
                        logging.debug("Rethrew exception")
                        raise e
                    logger.debug("%s" % (traceback.format_exc()))
                    logger.debug("attempt=%d" % attempt)
                    current_max_delay = min(max_delay, base * 2 ** attempt)
                    logger.debug("delay_range=(%f %f)" % (min_delay, current_max_delay))
                    delay = random.uniform(min_delay, current_max_delay) # nosec
                    logger.debug("cumulative delay=%f max=%d" % (cumulative_delay, max_cumulative_delay))
                    logger.debug("Retrying in %f seconds..." % (delay))
                    time.sleep(delay)
                    cumulative_delay += delay
            return f(*args, **kwargs)

        return f_retry  # true decorator

    return deco_retry
