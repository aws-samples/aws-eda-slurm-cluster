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
import json
import logging
import logging.handlers
import os
import pprint
# Subprocess not being used to execute user supplied data
import subprocess # nosec
import yaml

logger = logging.getLogger(__file__)

class SlurmAccountManager:

    # Accounts and users that should never be deleted
    SYSTEM_ACCOUNTS = [
        'pcdefault',
        'root',
    ]
    SYSTEM_USERS = [
        'centos',
        'ec2-user',
        'rocky',
        'root',
        'slurm'
    ]
    def __init__(self, accounts_filename, users_filename, default_account):
        logger.info("")
        logger.info("Creating/updating Slurm users and groups")
        logger.info(f"Accounts filename: {accounts_filename}")

        with open(accounts_filename, 'r') as fh:
            self.accounts = yaml.safe_load(fh)
        with open(users_filename, 'r') as fh:
            self.users_groups = json.load(fh)
        self.default_account = default_account

        self.SLURM_ROOT = os.environ['SLURM_ROOT']
        self.sacctmgr = self.SLURM_ROOT + '/bin/sacctmgr'
        self.scontrol = self.SLURM_ROOT + '/bin/scontrol'
        self.sshare = self.SLURM_ROOT + '/bin/sshare'

        self.devnull = open(os.devnull, 'w')

        logger.debug(f"Configured accounts:\n{json.dumps(self.accounts, indent=4)}")

        # Get all mapped users
        self.users_to_accounts_map = {}
        for account in sorted(self.accounts.keys()):
            for user in self.accounts[account].get('users', []):
                if user not in self.users_to_accounts_map:
                    self.users_to_accounts_map[user] = []
                self.users_to_accounts_map[user].append(account)
        for user in sorted(self.users_to_accounts_map.keys()):
            logger.debug(f"{user} accounts: {self.users_to_accounts_map[user]}")
            if len(self.users_to_accounts_map[user]) > 1:
                logger.debug(f"{user:15s} mapped to multiple accounts: {sorted(self.users_to_accounts_map[user])}")

        # Make sure that all domain users are mapped to an account.
        # If not then map to the default account
        for user in sorted(self.users_groups['users'].keys()):
            if user not in self.users_to_accounts_map:
                logger.info(f"{user:15s} not assigned to account. Defaulting to {self.default_account}")
                if 'users' not in self.accounts[self.default_account]:
                    self.accounts[self.default_account]['users'] = []
                self.accounts[self.default_account]['users'].append(user)

        self.slurm_user_account_dict = self.get_slurm_user_account_dict()
        logger.debug(f"Current users and accounts in slurmdb:\n{json.dumps(self.slurm_user_account_dict, indent=4)}")

        number_of_changes = self.update_slurm()

        self.slurm_user_account_dict = self.get_slurm_user_account_dict()
        logger.debug(f"Current users and accounts in slurmdb:\n{json.dumps(self.slurm_user_account_dict, indent=4)}")

        number_of_changes = self.update_slurm()

        assert(number_of_changes == 0)

        logger.info(f"Success")
        return

    def update_slurm(self):
        number_of_changes = 0
        number_of_errors = 0
        # Create/update accounts
        logger.info(f"Create/update accounts:")
        for account in sorted(self.accounts.keys()):
            logger.debug(f"Checking account {account} existence and fairshare")
            account_info = self.accounts[account]
            description = self.accounts[account].get('description', 'none')
            organization = self.accounts[account].get('organization', 'none')
            fairshare = self.accounts[account].get('fairshare', 1)
            if account not in self.slurm_user_account_dict['accounts']:
                # Account doesn't exist so create it
                cmd = [self.sacctmgr, 'add', '-i', 'account', account, f'Description={description}', f'Organization={organization}', f'Fairshare={fairshare}']
                parent = account_info.get('parent', None)
                if parent:
                    cmd.append(f'Parent={parent}')
                logger.info(f"    Creating account {account} with fairshare={fairshare}, parent={parent}")
                try:
                    subprocess.check_output(cmd, encoding='UTF-8') # nosec
                    self.slurm_user_account_dict['accounts'][account] = {
                        'parent_name': parent,
                        'users': [],
                        'share': fairshare
                    }
                except subprocess.CalledProcessError as e:
                    logger.exception(f"Couldn't add account {account}.\ncommand: {e.cmd}\noutput:\n{e.output}")
                    number_of_errors += 1
                number_of_changes += 1
            else:
                # Account exists so make sure fairshare is correct
                act_fairshare = self.slurm_user_account_dict['accounts'][account]['share']
                if fairshare != int(act_fairshare):
                    logger.info(f'    Updating account {account} fairshare from {act_fairshare} to {fairshare}')
                    try:
                        subprocess.check_output([self.sacctmgr, 'modify', '-i', 'account', account, 'set', f'Fairshare={fairshare}'], encoding='UTF-8', stderr=self.devnull) # nosec
                    except subprocess.CalledProcessError as e:
                        logger.exception(f"Couldn't set fairshare for account {account}.\ncommand: {e.cmd}\noutput:\n{e.output}")
                        number_of_errors += 1
                    number_of_changes += 1

        # After all projects have been created, make sure that the parent's are correct
        for account in sorted(self.accounts.keys()):
            logger.debug(f"Checking account {account}'s parent")
            account_info = self.accounts[account]
            exp_parent = account_info.get('parent', 'root')
            act_parent = self.slurm_user_account_dict['accounts'][account]['parent_name']
            if exp_parent != act_parent:
                logger.info(f"Updating {account} account parent from {act_parent} to {exp_parent}")
                try:
                    subprocess.check_output([self.sacctmgr, 'modify', '-i', 'account', account, 'set', f'Parent={exp_parent}'], encoding='UTF-8', stderr=self.devnull) # nosec
                except subprocess.CalledProcessError as e:
                    logger.exception(f"Couldn't set ParentName for account {account} to {exp_parent}.\ncommand: {e.cmd}\noutput:\n{e.output}")
                    number_of_errors += 1
                number_of_changes += 1

        for user in sorted(self.users_to_accounts_map.keys()):
            user_accounts = self.users_to_accounts_map[user]
            default_account = user_accounts[0]
            if user not in self.slurm_user_account_dict['users']:
                # Create user
                logger.info(f"Creating user {user} with account={default_account}")
                try:
                    subprocess.run([self.sacctmgr, '-i', 'add', 'user', user, f'Account={default_account}'], check=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, encoding='UTF-8') # nosec
                except subprocess.CalledProcessError as e:
                    logger.exception(f"Couldn't add user {user}.\ncommand: {e.cmd}\noutput:\n{e.output}")
                    number_of_errors += 1
                number_of_changes += 1

            # Check to make sure that user is added to all accounts
            for account in user_accounts:
                if account in self.slurm_user_account_dict['users'].get(user, {}).get('accounts', {}):
                    continue
                # Add a new account to the user
                logger.info(f"Adding {account} account to user {user}")
                try:
                    subprocess.run([self.sacctmgr, '-i', 'add', 'user', user, f'account={account}'], check=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, encoding='UTF-8') # nosec
                except subprocess.CalledProcessError as e:
                    logger.info(f"Default account of {user} already {account}.")
                    if 'Nothing new added' not in e.output:
                        logger.exception(f"Couldn't change default account of {user} to {account}.\ncommand: {e.cmd}\noutput:\n{e.output}")
                    number_of_errors += 1
                number_of_changes += 1

        # Make sure default account of users is correct
        # A user must be assigned to an account before it can be made the default
        for user in sorted(self.users_to_accounts_map.keys()):
            user_accounts = self.users_to_accounts_map[user]
            default_account = user_accounts[0]
            # If this is a new user then self.slurm_user_account_dict won't have any information about it
            act_default_account = self.slurm_user_account_dict['users'].get(user, {}).get('default-account', None)
            if act_default_account and default_account != act_default_account:
                logger.info(f"Changing default account of {user:15s} from {act_default_account} to {default_account}")
                try:
                    subprocess.run([self.sacctmgr, '-i', 'modify', 'user', user, 'set', f'DefaultAccount={default_account}'], check=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, encoding='UTF-8') #nosec
                except subprocess.CalledProcessError as e:
                    logger.exception(f"Couldn't set default account of {user} to {default_account}.\ncommand: {e.cmd}\noutput:\n{e.output}")
                    number_of_errors += 1
                number_of_changes += 1

        # Delete old user/account associations
        logger.debug(f"Checking for users and accounts to be deleted:")
        for account in sorted(self.slurm_user_account_dict['accounts']):
            if account in self.SYSTEM_ACCOUNTS:
                logger.debug(f"    Skipping system account {account}")
                continue
            logger.debug(f"    Checking account {account}:")
            if account not in self.accounts:
                users_to_delete_from_account = self.slurm_user_account_dict['accounts'][account]['users']
                if not sorted(users_to_delete_from_account):
                    logger.info(f"        The {account} account exists in slurm but is not being used.")
                else:
                    logger.info(f"        The {account} account exists in slurm and has {len(users_to_delete_from_account)} users that will be removed from the account.")
            else:
                logger.info(f"        The {account} account exists in slurm and is being used.")
                users_to_delete_from_account = []
                for user in sorted(self.slurm_user_account_dict['accounts'][account]['users']):
                    if user not in self.accounts[account]['users']:
                        logger.debug(f"        Deleting user {user} from {account}")
                        users_to_delete_from_account.append(user)
            if users_to_delete_from_account:
                logger.debug(f"        Deleting {len(users_to_delete_from_account)} users from {account}")
            for user in users_to_delete_from_account:
                if user in self.SYSTEM_USERS:
                    logger.debug(f"        Skipping system user {user}")
                    continue
                logger.info(f"        Deleting user {user} from account {account}")
                try:
                    subprocess.run([self.sacctmgr, '-i', 'delete', 'user', user, 'where', f'Account={account}'], check=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, encoding='UTF-8') #nosec
                except subprocess.CalledProcessError as e:
                    logger.error(f"Couldn't delete user {user} from account {account}.\ncommand: {e.cmd}\noutput:\n{e.output}")
                    number_of_errors += 1
                number_of_changes += 1

            # Delete unused accounts
            if account not in self.accounts:
                logger.debug(f"        Deleting account {account}")
                try:
                    subprocess.run([self.sacctmgr, '-i', 'delete', 'account', account], check=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, encoding='UTF-8') #nosec
                except subprocess.CalledProcessError as e:
                    logger.error(f"Couldn't delete user {user} from account {account}.\ncommand: {e.cmd}\noutput:\n{e.output}")
                    number_of_errors += 1
                number_of_changes += 1

        logger.debug(f"Delete unconfigured users")
        for user in sorted(self.slurm_user_account_dict['users']):


        if number_of_errors:
            raise RuntimeError("Some slurm updates failed")

        return number_of_changes

    def get_slurm_user_account_dict(self):
        logger.debug(f"get_slurm_user_account_dict()")
        user_account_dict = {
            'accounts': {},
            'users': {}
        }
        logger.debug(f"Get all user associations:")
        try:
            lines = subprocess.check_output([self.sacctmgr, '--noheader', '--parsable2', 'list', 'assoc', 'format=Cluster,Account,User,Share,ParentName'], stderr=self.devnull, encoding='UTF-8').split('\n') # nosec
        except subprocess.CalledProcessError as e:
            logger.exception(f"Couldn't list associations.\ncommand: {e.cmd}\noutput:\n{e.output}")
            raise
        for line in lines:
            if len(line) == 0: continue
            #logger.debug(f"{line}")
            (cluster,account,user,share,parent_name) = line.split('|')
            logger.debug(f"    account={account:15s} user={user:15s} share={share:5s} parent={parent_name}")
            if user:
                if user not in user_account_dict['users']:
                    user_account_dict['users'][user] = {
                        'default-account': None,
                        'accounts': {}
                    }
                user_account_dict['users'][user]['accounts'][account] = share

            if account not in user_account_dict['accounts']:
                user_account_dict['accounts'][account] = {
                    'parent_name': 'root',
                    'users': [],
                    'share': 1
                }
            if parent_name:
                user_account_dict['accounts'][account]['parent_name'] = parent_name
            if user:
                user_account_dict['accounts'][account]['users'].append(user)
            else:
                user_account_dict['accounts'][account]['share'] = int(share)

        logger.debug(f"Get the default account for each user:")
        try:
            lines = subprocess.check_output([self.sacctmgr, '--noheader', '--parsable2', 'list', 'users', 'format=User,DefaultAccount'], stderr=self.devnull, encoding='UTF-8').split('\n') # nosec
        except subprocess.CalledProcessError as e:
            logger.exception(f"Couldn't list users.\ncommand: {e.cmd}\noutput:\n{e.output}")
            raise
        logger.debug("Get default accounts for users")
        for line in lines:
            logger.debug(f"{line}")
            if len(line) == 0: continue
            (user, default_account) = line.split('|')
            if user not in user_account_dict['users']:
                user_account_dict['users'][user] = {
                    'default-account': None,
                    'accounts': {}
                }
            user_account_dict['users'][user]['default-account'] = default_account
        return user_account_dict

if __name__ == '__main__':
    logger_formatter = logging.Formatter('%(levelname)s:%(asctime)s: %(message)s')
    logger_rotatingFileHandler = logging.handlers.RotatingFileHandler(filename='/var/log/slurm/create_slurm_accounts.log', mode='a', maxBytes=1000000, backupCount=10)
    logger_rotatingFileHandler.setFormatter(logger_formatter)
    logger.addHandler(logger_rotatingFileHandler)
    logger.setLevel(logging.INFO)

    try:
        parser = argparse.ArgumentParser("Create/update slurm accounts")
        parser.add_argument('--accounts', dest='accounts', action='store', required=True, help="accounts input filename")
        parser.add_argument('--users', dest='users', action='store', required=True, help="users/groups input filename")
        parser.add_argument('--default-account', action='store', required=True, help="Default account for users")
        parser.add_argument('--debug', '-d', action='count', default=False, help="Enable debug messages")
        args = parser.parse_args()

        if args.debug:
            logger.setLevel(logging.DEBUG)
            stream_handler = logging.StreamHandler()
            stream_handler.setFormatter(logger_formatter)
            logger.addHandler(stream_handler)

        app = SlurmAccountManager(args.accounts, args.users, args.default_account)
    except:
        logging.exception(f"Unhandled exception in {__file__}")
        raise
