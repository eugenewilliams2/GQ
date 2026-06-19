#!/usr/bin/env bash
# Redeploy the storefront to GitHub Pages.
# Usage:
#   bash scripts/deploy.sh                  # publish the landing page
#   bash scripts/deploy.sh aispecialists.com  # also attach a custom domain (CNAME)
#
# Live URL: https://eugenewilliams2.github.io/ai-specialists/
# NOTE: only index.html is published. The product PDF/.md is the PAID file —
#       upload that to Gumroad, never to the public site.
set -e
REPO="eugenewilliams2/ai-specialists"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BUILD="/tmp/ai-specialists-deploy"
DOMAIN="$1"

rm -rf "$BUILD" && mkdir -p "$BUILD"
cp "$ROOT/store/index.html" "$BUILD/index.html"
cp "$BUILD/index.html" "$BUILD/404.html"
: > "$BUILD/.nojekyll"
[ -n "$DOMAIN" ] && echo "$DOMAIN" > "$BUILD/CNAME" && echo "→ CNAME set to $DOMAIN"

git -C "$BUILD" init -q
git -C "$BUILD" add -A
git -C "$BUILD" -c user.email="eugenewilliams713@gmail.com" -c user.name="Eugene Williams" \
  commit -qm "Deploy storefront $(date +%Y-%m-%d_%H:%M)"
git -C "$BUILD" branch -M main
git -C "$BUILD" remote add origin "https://github.com/$REPO.git" 2>/dev/null || true
git -C "$BUILD" push -u origin main --force

echo "✅ Deployed → https://eugenewilliams2.github.io/ai-specialists/"
[ -n "$DOMAIN" ] && echo "   After DNS points to GitHub, also live at https://$DOMAIN"
