#!/bin/bash
# Clear Python bytecode cache to fix NameError issues
# Run this script after pulling new code to production

echo "Clearing Python bytecode cache..."

# Find and remove all .pyc files
find . -type f -name "*.pyc" -delete

# Find and remove all __pycache__ directories
find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null

echo "Cache cleared successfully!"
echo "Restart your application server for changes to take effect."
