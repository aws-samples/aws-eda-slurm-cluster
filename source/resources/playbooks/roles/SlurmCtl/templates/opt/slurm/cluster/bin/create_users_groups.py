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

import argparse
import grp
import json
import logging
import pprint
import re
import subprocess

logger = logging.getLogger(__file__)
logger_formatter = logging.Formatter('%(levelname)s: %(message)s')
logger_streamHandler = logging.StreamHandler()
logger_streamHandler.setFormatter(logger_formatter)
logger.addHandler(logger_streamHandler)
logger.setLevel(logging.INFO)

pp = pprint.PrettyPrinter(indent=4)

def main(filename):
    with open(filename, 'r') as fh:
        config = json.load(fh)
    invalid_gids = []
    for gid in config['gids'].keys():
        group_name = config['gids'][gid]
        if int(gid) < 1024 or group_name in ['nfsnobody']:
            logger.debug(f"Skipping privileged group {group_name}({gid})")
            invalid_gids.append(gid)
            continue
        logger.debug("Creating group {}({})".format(gid, group_name))
        try:
            subprocess.check_output(['groupadd', '-g', gid, group_name], stderr=subprocess.STDOUT)
        except subprocess.CalledProcessError as e:
            lines = e.output.decode('utf-8')
            if 'is not a valid group name' in lines:
                logger.info("group {}({}) is not a valid group name".format(gid, group_name))
                invalid_gids.append(gid)
            elif 'already exists' in lines:
                logger.info("group {}({}) already exists".format(gid, group_name))
            else:
                logger.exception(f"group add of {group_name}({gid}) failed. output:\n{lines}")
    logger.debug("invalid_gids: {}".format(invalid_gids))
    for user in sorted(config['users'].keys()):
        uid = config['users'][user]['uid']
        if int(uid) < 1024 or user in ['nfsnobody']:
            logger.debug(f"Skipping privileged group {group_name}({gid})")
            continue
        logger.debug("Creating user {}({})".format(uid, user))
        gid = config['users'][user]['gid']
        logger.debug("gid: {}".format(gid))
        if gid in invalid_gids:
            logger.debug('gid is invalid')
            continue
        gids = config['users'][user]['gids']
        logger.debug("gids: {}".format(gids))
        for invalid_gid in invalid_gids:
            logger.debug("invalid gid: {}".format(invalid_gid))
            if invalid_gid in gids:
                logger.debug("Removed {}".format(invalid_gid))
                gids.remove(invalid_gid)
        useradd_args = ['useradd', '--uid', uid, '--gid', gid, '--groups', ','.join(gids), user, '--no-create-home']
        if config['users'][user].get('home', None):
            useradd_args.append('--home-dir')
            useradd_args.append(config['users'][user]['home'])
        try:
            subprocess.check_output(useradd_args, stderr=subprocess.STDOUT)
        except subprocess.CalledProcessError as e:
            lines = e.output.decode('utf-8')
            logger.debug(f"lines:\n{lines}")
            if 'is not a valid group name' in lines:
                logger.info("group {}({}) is not a valid group name".format(gid, group_name))
                invalid_gids.append(gid)
            elif 'already exists' in lines:
                logger.info("group {}({}) already exists".format(gid, group_name))
            else:
                logger.exception(f"group add of {user}({uid}) failed. output:\n{lines}")

if __name__ == '__main__':
    parser = argparse.ArgumentParser("Create users/groups using info from a json file")
    parser.add_argument('-i', dest='filename', action='store', required=True, help="input filename")
    parser.add_argument('--debug', '-d', action='count', default=False, help="Enable debug messages")
    args = parser.parse_args()

    logger_formatter = logging.Formatter('%(levelname)s:%(asctime)s: %(message)s')
    logger_streamHandler = logging.StreamHandler()
    logger_streamHandler.setFormatter(logger_formatter)
    logger.addHandler(logger_streamHandler)
    logger.setLevel(logging.INFO)
    if args.debug:
        logger.setLevel(logging.DEBUG)

    main(args.filename)
