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

"""
Create an LDIF file that creates 10 admins, 2 groups, and 100 users per group.
"""

import logging
import os
import os.path
from os.path import dirname, realpath
from textwrap import dedent

config = {
    'OU': 'CORP',
    'DC': 'corp,dc=res,dc=com',
    'DirectoryDomain': 'corp.res.com',
    'groups': [
        {
            'prefix': 'group',
            'OU': None,
            'first_gid': 2000,
            'index0': 1,
            'number': 2,
            'description': 'Non-RES group'
        },
        {
            'name': 'RESAdministrators',
            'OU': 'RES',
            'gid': 2020,
            'description': 'Represents the group of sudoers'
        }
    ],
    'users': [
        {
            'prefix': 'admin',
            'OU': None,
            'number': 10,
            'first_uid': 3000,
            'first_gid': 4000,
            'groups': [
                'RESAdministrators',
                'group01',
                'group02'
            ]
        },
        {
            'prefix': 'user',
            'OU': None,
            'number': 100,
            'first_uid': 5000,
            'first_gid': 6000,
            'groups': [
                'group01'
            ]
        },
        {
            'prefix': 'user',
            'OU': None,
            'number': 100,
            'first_index': 101,
            'first_uid': 5100,
            'first_gid': 6100,
            'groups': [
                'group02'
            ]
        }
    ]
}

logger = logging.getLogger(__file__)
logger_formatter = logging.Formatter('%(levelname)s: %(message)s')
logger_streamHandler = logging.StreamHandler()
logger_streamHandler.setFormatter(logger_formatter)
logger.addHandler(logger_streamHandler)
logger.propagate = False
logger.setLevel(logging.INFO)

# Use script location as current working directory
script_directory = os.path.dirname(os.path.realpath(f"{__file__}"))
logger.info(f"Working directory: {script_directory}")
os.chdir(script_directory)

fh = open('res-demo-with-cidr/res.ldif', 'w')

fh.write(dedent("""
                # Create a OU to be used by RES
                dn: OU=RES,OU=${OU},DC=${DC}
                changetype: add
                objectClass: top
                objectClass: organizationalUnit
                ou: RES
                description: The RES application will limit syncing groups and group-members in the RES OU

                # Create a OU to be used by RES to create computers
                dn: OU=Computers,OU=RES,OU=${OU},DC=${DC}
                changetype: add
                objectClass: top
                objectClass: organizationalUnit
                ou: Computers
                description: The RES application will limit creating computers to this OU

                # Create a OU to be used by RES to create groups and add users to
                dn: OU=Users,OU=RES,OU=${OU},DC=${DC}
                changetype: add
                objectClass: top
                objectClass: organizationalUnit
                ou: Users
                description: The RES application will limit syncing groups and group-members in the RES OU
                """))

group_members = {}
for user_dict in config['users']:
    user_prefix = user_dict['prefix']
    first_index = user_dict.get('first_index', 1)
    for user_index in range(first_index, first_index + user_dict['number']):
        userid = user_prefix + f"{user_index:04}"
        ou = user_dict['OU']
        comment = f"Create a user: {userid}"
        if ou:
            comment += f" in {ou} OU"
        dn = f"CN={userid},OU=Users,"
        if ou:
            dn += f"OU={ou},"
        dn += "OU=${OU},DC=${DC}"
        fh.write(dedent(f"""
                        {comment}
                        dn: {dn}
                        changetype: add
                        objectClass: top
                        objectClass: person
                        objectClass: organizationalPerson
                        objectClass: user
                        cn: {userid}
                        sAMAccountName: {userid}
                        name: {userid}
                        userPrincipalName: {userid}@${{DirectoryDomain}}
                        mail: {userid}@${{DirectoryDomain}}
                        uidNumber: {user_dict['first_uid']+user_index}
                        gidNumber: {user_dict['first_gid']+user_index}
                        unixHomeDirectory: /home/{userid}
                        loginShell: /bin/bash
                        """))
        for group in user_dict['groups']:
            if group not in group_members:
                group_members[group] = []
            group_members[group].append(dn)

for group_dict in config['groups']:
    ou = group_dict['OU']
    for group_index in range(group_dict.get('index0', 1), group_dict.get('number', 1) + 1):
        if 'index0' in group_dict:
            group_name = f"{group_dict['prefix']}{group_index:02}"
            gid = group_dict['first_gid'] + group_index
        else:
            group_name = group_dict['name']
            gid = group_dict['gid']
        comment = f"# Create a group: {group_name}"
        if ou:
            comment += f" in {ou} OU"
        dn = f"CN={group_name},OU=Users,"
        if ou:
            dn += f"OU={ou},"
        dn += "OU=${OU},DC=${DC}"
        fh.write(dedent(f"""
                        {comment}
                        dn: {dn}
                        changetype: add
                        objectClass: top
                        objectClass: group
                        cn: {group_name}
                        description: {group_dict['description']}
                        distinguishedName: {dn}
                        name: {group_name}
                        sAMAccountName: {group_name}
                        objectCategory: CN=Group,CN=Schema,CN=Configuration,DC=${{DC}}
                        gidNumber: {gid}
                        """))
        for member_dn in group_members.get(group_name, []):
            fh.write(f"member: {member_dn}\n")
