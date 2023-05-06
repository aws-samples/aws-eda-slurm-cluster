#!/usr/bin/env python3

import argparse
import boto3
from botocore.exceptions import NoCredentialsError
import json
import logging
from sys import exit

logger = logging.getLogger(__file__)
logger_formatter = logging.Formatter('%(levelname)s:%(asctime)s: %(message)s')
logger_streamHandler = logging.StreamHandler()
logger_streamHandler.setFormatter(logger_formatter)
logger.addHandler(logger_streamHandler)
logger.setLevel(logging.INFO)
logger.propagate = False

class SavingsPlanInfo:

    VALID_SAVINGS_PLAN_TYPES = [
        'EC2Instance',
        'Compute'
    ]
    VALID_DURATIONS = [1, 3]
    VALID_PAYMENT_OPTIONS = [
        'All Upfront',
        'Partial Upfront',
        'No Upfront'
    ]

    def __init__(self, region: str):
        self._region = region
        self._savingsplans_client = boto3.client('savingsplans', region_name=region)

    def get_ec2_savings_plan_rate(self, instance_type: str, duration_years: int, payment_option: str):
        '''
        Get the hourly rate for the specified instance type and EC2 Saving Plan terms

        Args:
            instance_type (str): EC2 instance type
            duration_years (int): Duration in years. 1 or 3
            payment_option (str): 'All Upfront'|'Partial Upfront'|'No Upfront'
        Returns:
            float: The effective hourly rate for the savings plan
        '''
        assert duration_years in SavingsPlanInfo.VALID_DURATIONS
        assert payment_option in SavingsPlanInfo.VALID_PAYMENT_OPTIONS

        instance_family = instance_type.split('.')[0]
        response = self._savingsplans_client.describe_savings_plans_offerings(
            productType = 'EC2',
            planTypes=['EC2Instance'],
            currencies=['USD'],
            filters=[
                {'name': 'region', 'values': [self._region]},
                {'name': 'instanceFamily', 'values': [instance_family]},
            ],
            durations=[duration_years * 365 * 24 * 60 * 60],
            paymentOptions=[payment_option],
        )['searchResults']
        logger.debug(f"offerIDs:\n{json.dumps(response, indent=4)}")
        if not response:
            return None
        offeringId = response[0]['offeringId']

        response = self._savingsplans_client.describe_savings_plans_offering_rates(
            savingsPlanOfferingIds=[offeringId],
            products=['EC2'],
            serviceCodes=['AmazonEC2'], # 'Compute'
            savingsPlanTypes=['EC2Instance'],
            savingsPlanPaymentOptions=[payment_option],
            filters=[
                {'name': 'region', 'values': [self._region]},
                {'name': 'instanceType', 'values': [instance_type]},
                {'name': 'productDescription', 'values': ['Linux/UNIX']},
                {'name': 'tenancy', 'values': ['shared']},
            ],
            # usageTypes=[
            #     'string',
            # ],
        )['searchResults']
        logger.debug(json.dumps(response, indent=4))
        if not response:
            return None
        return float(response[0]['rate'])

    def get_compute_savings_plan_rate(self, instance_type: str, duration_years: int, payment_option: str):
        '''
        Get the hourly rate for the specified instance type and EC2 Saving Plan terms

        Args:
            instance_type (str): EC2 instance type
            duration_years (int): Duration in years. 1 or 3
            payment_option (str): 'All Upfront'|'Partial Upfront'|'No Upfront'
        Returns:
            float: The effective hourly rate for the savings plan
        '''
        assert duration_years in SavingsPlanInfo.VALID_DURATIONS
        assert payment_option in SavingsPlanInfo.VALID_PAYMENT_OPTIONS

        response = self._savingsplans_client.describe_savings_plans_offerings(
            planTypes=['Compute'],
            currencies=['USD'],
            durations=[duration_years * 365 * 24 * 60 * 60],
            paymentOptions=[payment_option],
        )['searchResults']
        if not response:
            return None
        logger.debug(f"offerings:\n{json.dumps(response, indent=4)}")
        offeringId = response[0]['offeringId']

        response = self._savingsplans_client.describe_savings_plans_offering_rates(
            savingsPlanOfferingIds=[offeringId],
            serviceCodes=['AmazonEC2'],
            savingsPlanPaymentOptions=[payment_option],
            filters=[
                {'name': 'region', 'values': [self._region]},
                {'name': 'instanceType', 'values': [instance_type]},
                {'name': 'productDescription', 'values': ['Linux/UNIX']},
                {'name': 'tenancy', 'values': ['shared']},
            ],
        )['searchResults']
        logger.debug(f"rates:\n{json.dumps(response, indent=4)}")
        if not response:
            return None
        return float(response[0]['rate'])

def main():
    try:
        parser = argparse.ArgumentParser(description="Get Savings Plans rate for an EC2 instance type", formatter_class=argparse.ArgumentDefaultsHelpFormatter)
        parser.add_argument("--region", "-r", type=str, required=True, help="AWS region get info for.")
        parser.add_argument("--instance-type", type=str, required=True, help="EC2 instance type")
        parser.add_argument("--savings-plan-type", type=str, required=True, choices=SavingsPlanInfo.VALID_SAVINGS_PLAN_TYPES, help="Savings plan type.")
        parser.add_argument("--duration", type=int, required=True, choices=SavingsPlanInfo.VALID_DURATIONS, help="Savings plan duration in years.")
        parser.add_argument("--payment-option", type=str, required=True, choices=SavingsPlanInfo.VALID_PAYMENT_OPTIONS, help="Savings plan payment option.")
        parser.add_argument("--debug", "-d", action='store_const', const=True, default=False, help="Enable debug messages")
        args = parser.parse_args()

        if args.debug:
            logger.setLevel(logging.DEBUG)

        savingsPlanInfo = SavingsPlanInfo(args.region)
        if args.savings_plan_type == 'EC2Instance':
            rate = savingsPlanInfo.get_ec2_savings_plan_rate(args.instance_type, duration_years=args.duration, payment_option='All Upfront')
        elif args.savings_plan_type == 'Compute':
            rate = savingsPlanInfo.get_compute_savings_plan_rate(args.instance_type, duration_years=args.duration, payment_option='All Upfront')
        else:
            raise ValueError(f'Invalid --savings-plan-type {args.savings_plan_type}')
        print(f"{rate}")
    except NoCredentialsError as e:
        print('No AWS credentials found')
        sys.exit(1)

if __name__ == '__main__':
    main()
