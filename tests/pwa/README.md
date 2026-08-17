# Day screen tests

The PWA is a plain HTML app with no build step, so these run the real
`app.js` against the real `index.html` in a DOM, faking only the network.

    cd tests/pwa && npm install     # once
    node --test --test-force-exit

`pytest` runs them too, via `tests/test_pwa_js.py`, and skips them when node
or the dependencies are missing.

Every test here is a bug that reached the phone. When fixing a screen bug,
add the case first and watch it fail against the unfixed file — a test that
has never failed proves nothing.
