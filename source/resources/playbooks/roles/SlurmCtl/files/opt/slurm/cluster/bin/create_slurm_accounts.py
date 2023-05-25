#!/usr/bin/env python3.8
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
import os
import pprint
import re
# Subprocess not being used to execute user supplied data
import subprocess # nosec
import sys
import yaml

logger = logging.getLogger(__file__)

pp = pprint.PrettyPrinter(indent=4)

class SlurmAccountManager:
    def __init__(self, cluster, accounts_filename, users_filename, default_account):
        self.cluster = cluster
        with open(accounts_filename, 'r') as fh:
            self.accounts = yaml.safe_load(fh, Loader=yaml.FullLoader)
        with open(users_filename, 'r') as fh:
            self.users_groups = json.load(fh)
        self.default_account = default_account

        self.SLURM_ROOT = os.environ['SLURM_ROOT']
        self.sacctmgr = self.SLURM_ROOT + '/bin/sacctmgr'
        self.scontrol = self.SLURM_ROOT + '/bin/scontrol'
        self.sshare = self.SLURM_ROOT + '/bin/sshare'

        self.devnull = open(os.devnull, 'w')

        logger.debug("accounts:\n{}".format(pp.pformat(self.accounts)))
        self.user_account_dict = self.get_slurm_user_account_dict()
        logger.debug("users:\n{}".format(pp.pformat(self.user_account_dict)))

        # Get all mapped users
        mapped_users = {}
        for account in sorted(self.accounts.keys()):
            for user in self.accounts[account].get('users', []):
                if user in mapped_users:
                    logger.error("{} already mapped to multiple accounts: {} and {}".format(user, mapped_users[user], account))
                else:
                    mapped_users[user] = account

        # Make sure that all domain users are mapped to an account.
        # If not then map to the default account
        for user in sorted(self.users_groups['users'].keys()):
            if user not in mapped_users:
                logger.info("Assigning {:15s} to {}".format(user, self.default_account))
                if 'users' not in self.accounts[self.default_account]:
                    self.accounts[self.default_account]['users'] = []
                self.accounts[self.default_account]['users'].append(user)

        # Create/update accounts
        for account in sorted(self.accounts.keys()):
            logger.debug("Checking account {}".format(account))
            account_info = self.accounts[account]
            description = self.accounts[account].get('description', 'none')
            organization = self.accounts[account].get('organization', 'none')
            fairshare = self.accounts[account].get('fairshare', 1)
            try:
                line = subprocess.check_output([self.sacctmgr, '--noheader', '--parsable2', 'list', 'account', account, 'format=Account,Fairshare'], stderr=self.devnull, encoding='UTF-8').split('\n')[0] # nosec
            except subprocess.CalledProcessError as e:
                logger.exception(f"Couldn't get fairshare for {account}.\ncommand: {e.cmd}\noutput:\n{e.output}")
                raise
            logger.debug("Account info: {}".format(line))
            if len(line):
                try:
                    line = subprocess.check_output([self.sshare, '--noheader', '--parsable2', '-A', account, '--format=Account,RawShares'], stderr=self.devnull, encoding='UTF-8').split('\n')[0] #nosec
                except subprocess.CalledProcessError as e:
                    logger.exception(f"Couldn't get RawShares for {account}.\ncommand: {e.cmd}\noutput:\n{e.output}")
                    raise
                logger.debug("line={}".format(line))
                act_fairshare = line.split('|')[1]
                if fairshare != int(act_fairshare):
                    logger.info('Updating account {} fairshare from {} to {}'.format(account, act_fairshare, fairshare))
                    try:
                        subprocess.check_output([self.sacctmgr, 'modify', '-i', 'account', account, 'set', 'Fairshare={}'.format(fairshare)], encoding='UTF-8', stderr=self.devnull) # nosec
                    except subprocess.CalledProcessError as e:
                        logger.exception(f"Couldn't set fairshare for {account}.\ncommand: {e.cmd}\noutput:\n{e.output}")
                        raise
            else:
                logger.info("Creating account {}".format(account))
                cmd = [self.sacctmgr, 'add', '-i', 'account', account, 'Description={}'.format(description), 'Organization={}'.format(organization), 'Fairshare={}'.format(fairshare)]
                parent = self.accounts[account].get('parent', None)
                if parent:
                    cmd.append('Parent={}'.format(parent))
                try:
                    subprocess.check_output(cmd, encoding='UTF-8') # nosec
                except subprocess.CalledProcessError as e:
                    logger.exception(f"Couldn't add account for {account}.\ncommand: {e.cmd}\noutput:\n{e.output}")
                    raise

            # Make sure default account of users is correct
            for user in account_info.get('users', []):
                logger.debug("Checking if user {:15s} is assigned to account {}".format(user, account))
                try:
                    line = subprocess.check_output([self.sacctmgr, '--noheader', '--parsable2', 'list', 'user', user, 'format=User,DefaultAccount'], encoding='UTF-8', stderr=self.devnull).split('\n')[0] # nosec
                except subprocess.CalledProcessError as e:
                    logger.exception(f"Couldn't list account for {user}.\ncommand: {e.cmd}\noutput:\n{e.output}")
                    raise
                if len(line) == 0:
                    # Create user
                    logger.info("Creating user {} with account={}".format(user, account))
                    try:
                        subprocess.run([self.sacctmgr, '-i', 'add', 'user', user, 'Account={}'.format(account)], check=True, capture_output=True, encoding='UTF-8') # nosec
                    except subprocess.CalledProcessError as e:
                        logger.exception(f"Couldn't add user {user}.\ncommand: {e.cmd}\noutput:\n{e.output}")
                        raise
                else:
                    defaultAccount = line.split('|')[1]
                    if defaultAccount != account:
                        logger.info("Changing default account of {user:15s} from {defaultAccount} to {account}")
                        # Add a new account to the user
                        try:
                            result = subprocess.run([self.sacctmgr, '-i', 'add', 'user', user, f'account={account}',], check=True, capture_output=True, encoding='UTF-8') # nosec
                        except subprocess.CalledProcessError as e:
                            logging.info("Default account of {user} already {account}.")
                            if 'Nothing new added' not in e.output:
                                logger.exception(f"Couldn't change default account of {user} to {account}.\ncommand: {e.cmd}\noutput:\n{e.output}")
                                raise
                        try:
                            result = subprocess.run([self.sacctmgr, '-i', 'modify', 'user', user, 'set', 'DefaultAccount={}'.format(account),], check=True, capture_output=True, encoding='UTF-8') #nosec
                        except subprocess.CalledProcessError as e:
                            logger.exception(f"Couldn't set default account of {user} to {account}.\ncommand: {e.cmd}\noutput:\n{e.output}")
                            raise

    def get_slurm_user_account_dict(self):
        try:
            lines = subprocess.check_output([self.sacctmgr, '--noheader', '--parsable2', 'list', 'users', 'format=User%15,DefaultAccount%20'], stderr=self.devnull, encoding='UTF-8').split('\n') # nosec
        except subprocess.CalledProcessError as e:
            logger.exception(f"Couldn't list users.\ncommand: {e.cmd}\noutput:\n{e.output}")
            raise
        user_account_dict = {}
        for line in lines:
            if len(line) == 0: continue
            logger.debug(line)
            (user, account) = line.split('|')
            user_account_dict[user] = account
        return user_account_dict

if __name__ == '__main__':
    logger_formatter = logging.Formatter('%(levelname)s:%(asctime)s: %(message)s')
    logger_rotatingFileHandler = logging.handlers.RotatingFileHandler(filename='/var/log/slurm/create_slurm_accounts.log', mode='a', maxBytes=1000000, backupCount=10)
    logger_rotatingFileHandler.setFormatter(logger_formatter)
    logger.addHandler(logger_rotatingFileHandler)
    logger.setLevel(logging.INFO)

    try:
        parser = argparse.ArgumentParser("Create/update slurm accounts")
        parser.add_argument('--cluster', dest='cluster', action='store', required=True, help="Name of the slurm cluster")
        parser.add_argument('--accounts', dest='accounts', action='store', required=True, help="accounts input filename")
        parser.add_argument('--users', dest='users', action='store', required=True, help="users/groups input filename")
        parser.add_argument('--default-account', action='store', required=True, help="Default account for users")
        parser.add_argument('--debug', '-d', action='count', default=False, help="Enable debug messages")
        args = parser.parse_args()

        if args.debug:
            logger.setLevel(logging.DEBUG)

        app = SlurmAccountManager(args.cluster, args.accounts, args.users, args.default_account)
    except:
        logging.exception(f"Unhandled exception in {__file__}")
        raise
