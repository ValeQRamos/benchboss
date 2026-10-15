# Security policy

benchboss handles your ESPN session cookies (`espn_s2` and `SWID`), which give access to your
ESPN account. It stores them in the operating system keychain (or a 0600 file when no keychain
is available), sends them only to ESPN hosts, and never prints or logs them.

## Reporting a vulnerability

Please do not open a public issue. Email **[k1lldeer@proton.me](mailto:k1lldeer@proton.me)**
with a description and steps to reproduce. You will get an answer within a few days.

## If you think your cookies leaked

Sign out of espn.com in every browser (this invalidates the session), then run
`benchboss login` again.
