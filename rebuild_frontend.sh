#!/bin/bash
# Rebuild frontend to pick up latest changes

echo "🔨 Rebuilding frontend..."

cd web

# Clear any existing build
if [ -d "dist" ]; then
    echo "Removing old build..."
    rm -rf dist
fi

# Install dependencies if needed
if [ ! -d "node_modules" ]; then
    echo "Installing dependencies..."
    npm install
fi

# Build
echo "Building..."
npm run build

if [ $? -eq 0 ]; then
    echo ""
    echo "✅ Frontend rebuilt successfully!"
    echo ""
    echo "Next steps:"
    echo "1. Restart your backend server"
    echo "2. Hard refresh browser (Ctrl+Shift+R or Cmd+Shift+R)"
    echo "3. Check browser console for 'OpportunityCard data:' logs"
else
    echo ""
    echo "❌ Build failed! Check errors above."
    exit 1
fi
