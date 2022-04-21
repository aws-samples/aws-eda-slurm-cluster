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

import sys
from colored import fg, bg, attr
import getpass

def get_input(prompt, specified_value=None, expected_answers=None, expected_type=int, hide=False):
    if expected_answers is None:
        expected_answers = []
    response = None
    if specified_value:
        # Value specified, validating user provided input
        if expected_answers:
            if specified_value not in expected_answers:
                print(f"{fg('red')}{specified_value} is an invalid choice. Choose something from {expected_answers}{attr('reset')}")
                sys.exit(1)
        return specified_value

    else:
        # Value not specified, prompt user
        while isinstance(response, expected_type) is False:
            if sys.version_info[0] >= 3:
                if expected_answers:
                    question = input(f"{fg('misty_rose_3')} >> {prompt} {expected_answers}{attr('reset')}: ")
                else:
                    if hide is True:
                        question = getpass.getpass(prompt=f"{fg('misty_rose_3')} >> {prompt}{attr('reset')}: ")
                    else:
                        question = input(f"{fg('misty_rose_3')} >> {prompt}{attr('reset')}: ")
            else:
                # Python 2
                if expected_answers:
                    question = raw_input(f"{fg('misty_rose_3')} >> {prompt} {expected_answers}{attr('reset')}: ")
                else:
                    question = raw_input(f"{fg('misty_rose_3')} >> {prompt}{attr('reset')}: ")

            try:
                response = expected_type(question.rstrip().lstrip())
            except ValueError:
                print(f"Sorry, expected answer is something from {expected_answers}")


            if expected_answers:
                if response not in expected_answers:
                    print(f"{fg('red')}{response} is an invalid choice. Choose something from {expected_answers}{attr('reset')}")
                    response = None

    return response
