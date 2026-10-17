# Reusing optional saved work

First invocation: attach this skill in a matter chat and ask to save
"Alpha beta\nGamma" as notes. The model uses the workspace write tool.

Second invocation: attach the same skill in a new chat for that matter, ask to
read the saved notes and count their lines and words with the bundled helper.
The expected result is two lines and three words. A different matter and a
different user have independent workspaces.

These steps need the operator to enable workspace tools and the exact helper
bundle. Unconfigured tools are unavailable; the demonstration must say so.
