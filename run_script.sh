#!/bin/bash

echo "Running inside Rocky Linux 9 container"
echo "Python version: $(python3 --version)"
echo "Node.js version: $(node --version)"
echo "CDK version: $(cdk --version)"
echo ""
echo "Command line arguments received:"

# Print all received arguments
for arg in "$@"; do
    echo "- $arg"
done

# Demonstrate access to shared data
echo ""
echo "Contents of shared directory:"
ls -la /app/shared_data/

# Write to shared directory
echo "This file was created inside the container - $(date)" > /app/shared_data/container_file.txt
echo "Created a file in the shared directory: /app/shared_data/container_file.txt"

# You can add your specific script logic here
# For example, you might want to run a CDK command with the provided arguments:
# if [ "$1" == "deploy" ]; then
#     cdk deploy "$2"
# fi
