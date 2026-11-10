# A canonical repository file

This file stands in for something like `docs/quickstart.md`: a file that lives
in the repository, is maintained there, and is presented by a site page rather
than copied into one.

Its links are written relative to **its own** directory, which is the whole
point of the fixture — the transform has to resolve them from here, not from
the page that includes it.

See [the nested note](nested/deep.md) and the [launcher home screen](../../../../docs/images/launcher-home.png).

## Install

Two steps.

```sh
# A heading-shaped line inside a fence. The slicer must not stop here.
## Install
echo "not a heading"
```

### A subheading under Install

Kept, and demoted along with its parent when `shift=` is used.

## Troubleshooting

Everything after the `to=` heading, which the `from`/`to` fixture must exclude.
