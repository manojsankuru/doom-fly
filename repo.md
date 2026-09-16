doomfly/                 # upstream, untouched
  doom/                  # simulator, do not edit
  doom-ui/               # their viewer, reference only
flyview/                 # yours
  bridge.py              # subscribes :8766, republishes a slim JSON
  web/
    index.html           # three.js, fly avatar, arena, HUD
    fly.glb              # your model, original asset
    blueprint.html       # neuron graph view