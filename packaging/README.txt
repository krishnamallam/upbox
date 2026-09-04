upbox: see, audit, and control what your AI tools send to the cloud.

This disk image contains one command-line program, `upbox`. To install it:

    cp /Volumes/upbox/upbox /usr/local/bin/upbox
    chmod +x /usr/local/bin/upbox
    xattr -d com.apple.quarantine /usr/local/bin/upbox

The last line is needed because the binary is not signed with an Apple
Developer certificate; without it, Gatekeeper refuses to run downloaded
programs. Then:

    upbox init     # one-time CA install
    upbox start    # proxy + dashboard at http://127.0.0.1:8800

`upbox start` asks for your password the first time: OS-level capture needs
root. Everything upbox records stays on this machine; it makes no network
calls of its own.

Source, documentation, and the audit-log format: https://github.com/krishnamallam/upbox
