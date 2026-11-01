# Demo images

Numbered JPEG files are the source screenshots, played in filename order.
`netbox-cisco-sync-demo.gif` is the animation used in the project README.

The first image defines the viewport: 2330 × 1089 pixels. Taller images scroll
at 60 pixels per second, with a three-second initial hold and a one-second hold
at the bottom. Short images are shown for one second.

To rebuild, install Pillow and gifsicle, then run from the repository root:

```bash
python scripts/build_demo_gif.py
gifsicle -O1 --lossy=40 docs/images/netbox-cisco-sync-demo.gif -o /tmp/cisco-sync-demo.gif
mv /tmp/cisco-sync-demo.gif docs/images/netbox-cisco-sync-demo.gif
```

The publishable animation uses 64 colors and five frames per second to reduce
file size. Keep the source screenshots for future rebuilds. Review screenshots
for private data before rebuilding the animation.
