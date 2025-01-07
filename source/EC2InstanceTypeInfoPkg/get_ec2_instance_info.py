#!/usr/bin/env python3

import argparse
from botocore.exceptions import NoCredentialsError
from EC2InstanceTypeInfoPkg.EC2InstanceTypeInfo import EC2InstanceTypeInfo
import logging
from sys import exit
from VersionCheck import logger as VersionCheck_logger, VersionCheck

if __name__ == '__main__':
    try:
        parser = argparse.ArgumentParser(description="Get EC2 instance pricing info.", formatter_class=argparse.ArgumentDefaultsHelpFormatter)
        parser.add_argument("--region", "-r", type=str, default=[], action='append', help="AWS region(s) to get info for.")
        parser.add_argument("--input", '-i', type=str, default=None, help="JSON input file. Reads existing info from previous runs. Can speed up rerun if it failed to collect the data for a region.")
        parser.add_argument("--output-csv", '-o', type=str, default=None, help="CSV output file. Default: instance_type_info.csv")
        parser.add_argument("--disable-version-check", action='store_const', const=True, default=False, help="Disable git version check")
        parser.add_argument("--debug", "-d", action='store_const', const=True, default=False, help="Enable debug messages")
        args = parser.parse_args()

        if args.debug:
            VersionCheck_logger.setLevel(logging.DEBUG)

        if not args.disable_version_check and not VersionCheck().check_git_version():
            exit(1)

        if args.input:
            print(f"Reading existing instance info from {args.input}")
        ec2InstanceTypeInfo = EC2InstanceTypeInfo(args.region, json_filename=args.input, debug=args.debug)
        if args.output_csv:
            print(f"\nWriting output to CSV: {args.output_csv}")
            ec2InstanceTypeInfo.print_csv(args.output_csv)
    except NoCredentialsError as e:
        print('No AWS credentials found')
        exit(1)
