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

# Linux standard:
# 0-99: statically allocated by system
# 100-499: Reserved for dynamic allocation by system admins and post install scripts
# 500-999: Reserved
MIN_UID = 1000
MIN_GID = 1000

RESERVED_USERS = [
    'ec2-user',
    'nfsnobody',
    'ssm-user'
    ]

RESERVED_GROUPS = [
    'nfsnobody',
    ]

def main(filename):
    config = {}
    config['users'] = {}
    config['gids'] = {}
    try:
        users = subprocess.check_output(['wbinfo', '-u'], encoding='UTF-8').split()
    except FileNotFoundError:
        users = subprocess.check_output('getent passwd | cut -d: -f1', shell=True, encoding='UTF-8').split()
    logger.debug(f"Found {len(users)} users")
    for user in users:
        if ' ' in user:
            continue
        if '$' in user:
            continue
        logger.debug(f"User {user}:")
        if user in RESERVED_USERS:
            logger.debug(f"    Skipping reserved user")
            continue
        try:
            uid = subprocess.check_output(['id', '-u', user], encoding='UTF-8').split()[0]
        except subprocess.CalledProcessError:
            logger.debug(f"    Can't get uid of {user}")
            continue
        if int(uid) < MIN_UID:
            logger.debug(f"    Skipping {user} because uid={uid} < {MIN_UID}")
            continue
        gid = subprocess.check_output(['id', '-g', user], encoding='UTF-8').split()[0]
        logger.debug(f"    gid: {gid}")
        if int(gid) < MIN_GID:
            logger.debug(f"    Skipping {user} because gid={gid} < {MIN_GID}")
            continue
        all_gids = subprocess.check_output(['id', '-G', user], encoding='UTF-8').split('\n')[0].split(' ')
        logger.debug(f"    gids: {all_gids}")
        if not all_gids:
            logger.debug(f"    Skipping {user} because no gids found")
            continue
        gids = []
        for g in all_gids:
            if not g: # Ignore blank values
                continue
            if int(g) < MIN_GID:
                logger.debug(f"    Not using gid={g} because < {MIN_GID}")
                continue
            gids.append(g)
        gids = sorted(gids)
        try:
            home_dir = subprocess.check_output(f'getent passwd {user}| cut -d: -f6', shell=True, encoding='UTF-8').split()[0]
        except:
            logger.exception(f"    Couldn't get home dir for {user}")
            home_dir = ''
        config['users'][user] = {}
        config['users'][user]['uid'] = uid
        config['users'][user]['gid'] = gid
        config['users'][user]['gids'] = sorted(gids)
        config['users'][user]['home'] = home_dir

        for gid in config['users'][user]['gids']:
            config['gids'][str(gid)] = ''

    for gid in config['gids'].keys():
        group_name = get_group_name(int(gid))
        if group_name in RESERVED_GROUPS:
            continue
        config['gids'][gid] = group_name
    with open(filename, 'w') as fh:
        #fh.write(pp.pformat(config))
        json.dump(config, fh, sort_keys=True, indent=4)
    return

def get_group_name(gid):
    try:
        group_name = grp.getgrgid(gid).gr_name
    except KeyError:
        # Handle the case where a group doesn't have a name.
        # This can happen inside the container when a group name from AD is too long.
        group_name = str(gid)
    group_name = re.sub(r'^.+\\(.+)', r'\1', group_name)
    group_name = re.sub(r' ', r'_', group_name)
    return group_name


if __name__ == '__main__':
    parser = argparse.ArgumentParser("Write user/group info to a json file")
    parser.add_argument('-o', dest='filename', action='store', required=True, help="output filename")
    parser.add_argument('--debug', '-d', action='count', default=False, help="Enable debug messages")
    args = parser.parse_args()

    if args.debug:
        logger.setLevel(logging.DEBUG)

    main(args.filename)
