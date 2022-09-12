#!/usr/bin/env python3
"""
Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
SPDX-License-Identifier: MIT-0

Permission is hereby granted, free of charge, to any person obtaining a copy of this
software and associated documentation files (the "Software"), to deal in the Software
without restriction, including without limitation the rights to use, copy, modify,
merge, publish, distribute, sublicense, and/or sell copies of the Software, and to
permit persons to whom the Software is furnished to do so.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED,
INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A
PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT
HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION
OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE
SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
"""

import logging
from SlurmPlugin import SlurmPlugin
from sys import argv, exit

logger = logging.getLogger(__file__)
logger_formatter = logging.Formatter('%(levelname)s:%(asctime)s: %(message)s')
logger_rotatingFileHandler = logging.handlers.RotatingFileHandler(filename='/var/log/slurm/power_save.log', mode='a', maxBytes=1000000, backupCount=10)
logger_rotatingFileHandler.setFormatter(logger_formatter)
logger.addHandler(logger_rotatingFileHandler)
logger.setLevel(logging.INFO)

if __name__ == '__main__':
    try:
        logger.info("====================================================================================================")
        logger.info(f"{__file__} {argv[1:]}")
        logger.info("====================================================================================================")
        plugin = SlurmPlugin()
        rc = plugin.terminate()
    except:
        logging.exception(f"Unhandled exception in {__file__}")
        plugin.publish_cw_metrics(plugin.CW_UNHANDLED_TERMINATE_EXCEPTION, 1, [])
        rc = 1
    exit(rc)
